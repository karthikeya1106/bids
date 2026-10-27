"""
Safe reclassification of an already-stored dataset.

A dataset is ingested once, with whatever classifier existed at the time. When
the classifier improves, an old file can be stuck on a weaker template (usually
``generic``) even though its columns clearly describe a churn or sales table.
Re-uploading works, but it loses history and asks the user to find the file
again.

This service re-runs profiling, classification, mapping and validation against
the **stored** rows and applies the result only when the data itself supports
it:

* ownership is resolved from the dataset registry, never from the request body;
* user-confirmed (manual) mappings and targets are carried over when they are
  still valid, and reported for review when they are not;
* nothing is written when validation fails — the caller gets the blocking
  checks instead of a half-applied dataset;
* the canonical rows, dataset metadata, capability map and native analytics
  tables are updated together, so a retry cannot duplicate records;
* a content hash of the resulting canonical rows makes the operation
  idempotent: running it twice reports "unchanged" instead of rewriting, even
  though the second run reads canonical columns rather than the source ones.

No value is invented. If the stored rows only carry canonical fields (a dataset
ingested as sales or churn), reclassification works from those canonical
columns; a template whose required fields are absent is refused with an
explanation instead of being forced.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Optional

import pandas as pd
from sqlalchemy.orm import Session

from db.models import DatasetMeta, DatasetRow
from services.capabilities import build_capabilities
from services.classifier import classify_dataset
from services.ingestion import (
    _loads,
    _notes_for,
    build_records,
    dataset_payload,
    get_dataset,
    records_frame,
    set_active,
)
from services.mapping import DERIVED, GENERATE, score_field, suggest_mapping
from services.profiling import profile_dataframe
from services.schemas import SCHEMAS, DatasetSchema, get_schema
from services.validation import modules_supported, validate_dataset

# Columns that hold the platform's own bookkeeping rather than source data.
BOOKKEEPING = {"__row__"}

MODULE_ORDER = (
    "dashboard", "behavior", "segmentation", "rootcause", "drift", "forecast", "strategy", "analysis",
)


class ReclassifyError(Exception):
    """A refusal that should reach the client with a status code."""

    def __init__(self, message: str, status_code: int = 422, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _canonical_mapping(decisions: dict[str, dict]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for key, decision in decisions.items():
        if decision.get("status") == "derived":
            mapping[key] = DERIVED
        elif decision.get("value") == GENERATE or decision.get("status") == "generated":
            mapping[key] = GENERATE
        elif decision.get("column"):
            mapping[key] = decision["column"]
    return mapping


def _records_fingerprint(records: list[dict]) -> str:
    """Content hash of the canonical records.

    Idempotency is decided on the resulting rows, not on column names: a second
    run reads the freshly stored canonical columns instead of the original ones,
    so any signature built from source column names would differ even though the
    dataset is unchanged.
    """
    digest = hashlib.sha256()
    for record in records:
        # A missing value and an explicitly empty one mean the same thing to the
        # analytics, so they must not make the hashes differ.
        clean = {key: value for key, value in record.items() if value not in (None, "")}
        digest.update(json.dumps(clean, sort_keys=True, default=str).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()[:24]


def _before_snapshot(meta: DatasetMeta) -> dict:
    capabilities = _loads(meta.capabilities_json, {}) or {}
    schema = get_schema(meta.schema_kind)
    modules = capabilities.get("modules")
    statuses = {}
    if isinstance(modules, dict):
        for name, info in modules.items():
            statuses[name] = info.get("status") if isinstance(info, dict) else ("ready" if info else "unavailable")
    classification = capabilities.get("classification") or {}
    return {
        "schema": meta.schema_kind,
        "schema_label": schema.label,
        "task": meta.analysis_task,
        "target": meta.target_field,
        "rows": meta.row_count or 0,
        "confidence": classification.get("confidence"),
        "modules": statuses,
        "uploaded_at": str(meta.uploaded_at) if meta.uploaded_at else None,
    }


def _preserve_manual_mappings(
    schema: DatasetSchema,
    stored_decisions: dict[str, dict],
    columns: set[str],
    review: list[dict],
) -> dict[str, str]:
    """Carry over mappings the user chose by hand, when they still make sense."""
    overrides: dict[str, str] = {}
    for key, decision in stored_decisions.items():
        if decision.get("status") != "manual":
            continue
        column = decision.get("column")
        field = schema.field(key)
        if not column:
            continue
        if field is None:
            review.append({
                "kind": "mapping_dropped",
                "field": key,
                "column": column,
                "message": (
                    f"Your manual mapping '{decision.get('label') or key}' → '{column}' is not part of "
                    f"the {schema.label} template, so it was not carried over."
                ),
            })
            continue
        if column not in columns:
            review.append({
                "kind": "mapping_dropped",
                "field": key,
                "column": column,
                "message": (
                    f"Your manual mapping '{decision.get('label') or key}' → '{column}' no longer exists "
                    "in the stored columns, so it was not carried over."
                ),
            })
            continue
        overrides[key] = column
    return overrides


def _apply_manual_decisions(
    decisions: dict[str, dict],
    overrides: dict[str, str],
    frame: pd.DataFrame,
    profile: dict,
    schema: DatasetSchema,
) -> None:
    """Mark carried-over choices as manual and refresh their explanation."""
    columns = {column["name"]: column for column in profile["column_profiles"]}
    for key, column_name in overrides.items():
        decision = decisions.get(key)
        column = columns.get(column_name)
        if decision is None or column is None:
            continue
        spec = schema.field(key)
        scored = (
            score_field(spec, column_name, column, frame)
            if spec is not None
            else {"score": decision.get("score", 0.0), "reasons": []}
        )
        decision.update({
            "value": column_name,
            "column": column_name,
            "status": "manual",
            "confidence": "manual",
            "score": scored["score"],
            "reasons": ["kept from your earlier manual mapping"] + scored.get("reasons", []),
            "sample_values": column.get("sample_values", []),
            "source_dtype": column.get("dtype"),
        })


def _dedupe_mapping(
    schema: DatasetSchema,
    mapping: dict[str, str],
    decisions: dict[str, dict],
    review: list[dict],
) -> dict[str, str]:
    """One source column may feed at most one target field."""
    used: dict[str, str] = {}
    result = dict(mapping)
    for spec in schema.fields:
        key = spec.key
        column = result.get(key)
        if not column or column in (DERIVED, GENERATE):
            continue
        owner = used.get(column)
        if owner is None:
            used[column] = key
            continue
        # Keep the manual choice; drop the automatic duplicate.
        owner_decision = decisions.get(owner) or {}
        this_decision = decisions.get(key) or {}
        if owner_decision.get("status") == "manual" and this_decision.get("status") != "manual":
            result.pop(key, None)
            this_decision.update({
                "value": "", "column": None, "status": "unmapped", "confidence": "none", "score": 0.0,
                "reasons": [f"'{column}' is already mapped to '{owner_decision.get('label') or owner}'"],
            })
        elif this_decision.get("status") == "manual" and owner_decision.get("status") != "manual":
            result.pop(owner, None)
            owner_decision.update({
                "value": "", "column": None, "status": "unmapped", "confidence": "none", "score": 0.0,
                "reasons": [f"'{column}' is already mapped to '{this_decision.get('label') or key}' by you"],
            })
        else:
            result.pop(key, None)
            this_decision.update({
                "value": "", "column": None, "status": "unmapped", "confidence": "none", "score": 0.0,
                "reasons": [f"'{column}' is already used by another field"],
            })
            review.append({
                "kind": "mapping_conflict",
                "field": key,
                "column": column,
                "message": f"'{column}' was suggested for both '{owner}' and '{key}'; '{key}' was left unmapped.",
            })
    return result


def _drop_derived_sources(
    schema: DatasetSchema,
    mapping: dict[str, str],
    decisions: dict[str, dict],
) -> dict[str, str]:
    """A computed field must never be reused as an observed input.

    Canonical rows keep derived columns (for example ``total_charge_derived``),
    and their names resemble the field they were computed for. Mapping them back
    as an observed column would present a formula result as source data.
    """
    derived_keys = {spec.key for spec in schema.fields if spec.derive}
    if not derived_keys:
        return mapping
    result = dict(mapping)
    for key, column in list(result.items()):
        if key in derived_keys or column not in derived_keys:
            continue
        result.pop(key, None)
        decisions.setdefault(key, {}).update({
            "value": "",
            "column": None,
            "status": "unmapped",
            "confidence": "none",
            "score": 0.0,
            "reasons": [f"'{column}' is computed by this template, so it cannot also be an observed input"],
        })
    return result


def _target_key(
    schema: DatasetSchema,
    mapping: dict[str, str],
    frame: pd.DataFrame,
    stored_target: str,
) -> Optional[str]:
    """Translate a stored target into the new template's canonical key."""
    stored = (stored_target or "").strip()
    if not stored:
        return None
    if schema.field(stored):
        return stored
    for key, column in mapping.items():
        if column == stored:
            return key
    if stored in frame.columns and schema.custom:
        return stored
    return stored if stored in frame.columns and schema.id == "generic" else None


def _module_statuses(capabilities: dict) -> dict[str, str]:
    modules = capabilities.get("modules") or {}
    statuses: dict[str, str] = {}
    for name in MODULE_ORDER:
        info = modules.get(name)
        if isinstance(info, dict):
            statuses[name] = info.get("status") or "unavailable"
        elif isinstance(info, bool):
            statuses[name] = "ready" if info else "unavailable"
        else:
            statuses[name] = "unavailable"
    return statuses


def _mapping_diff(before: dict[str, str], after: dict[str, str], decisions: dict[str, dict]) -> list[dict]:
    changes: list[dict] = []
    for key in sorted(set(before) | set(after)):
        old = before.get(key) or ""
        new = after.get(key) or ""
        if old == new:
            continue
        decision = decisions.get(key) or {}
        changes.append({
            "field": key,
            "label": decision.get("label") or key,
            "before": old,
            "after": new,
            "status": decision.get("status"),
            "confidence": decision.get("confidence"),
        })
    return changes


# ─── Main operation ───────────────────────────────────────────────────────────


def reclassify_dataset(
    db: Session,
    owner_id: str,
    dataset_id: int,
    requested_schema: Optional[str] = None,
) -> dict:
    """Re-run classification and mapping for one stored dataset.

    Raises ``ReclassifyError`` when the dataset cannot be reclassified safely;
    the caller turns that into an HTTP error without touching the stored data.
    """
    meta = get_dataset(db, owner_id, dataset_id)
    if meta is None:
        raise ReclassifyError("Dataset not found.", status_code=404)

    before = _before_snapshot(meta)
    stored_caps = _loads(meta.capabilities_json, {}) or {}
    stored_decisions = _loads(meta.mapping_json, {}) or {}
    stored_mapping_json = meta.mapping_json
    stored_profile_json = meta.profile_json
    stored_canonical = _canonical_mapping(stored_decisions)
    stored_fingerprint = (stored_caps.get("classification") or {}).get("records_fingerprint")
    review: list[dict] = []
    notes: list[str] = []

    frame = records_frame(db, owner_id, dataset_id)
    if frame.empty:
        raise ReclassifyError(
            "This dataset has no stored rows, so it cannot be re-analysed. Upload the file again.",
            status_code=409,
        )
    work = frame.drop(columns=list(BOOKKEEPING), errors="ignore")
    source_kind = "source columns" if meta.schema_kind in {"generic", "custom"} else "canonical fields"
    if source_kind == "canonical fields":
        notes.append(
            "This dataset stores canonical fields only (it was ingested as "
            f"{get_schema(meta.schema_kind).label}), so re-analysis works from those columns. "
            "Upload the original file if you need the untouched source columns."
        )

    profile = profile_dataframe(work)
    classification = classify_dataset(work, profile)
    current = get_schema(meta.schema_kind)

    if requested_schema:
        if requested_schema not in SCHEMAS:
            raise ReclassifyError(f"Unknown analysis template '{requested_schema}'.", status_code=422)
        schema = get_schema(requested_schema)
        chosen_by = "requested"
    else:
        schema = get_schema(classification["schema"])
        chosen_by = "detected"
        if schema.id == "generic" and current.id != "generic":
            # Never downgrade a working domain template to generic coverage.
            schema = current
            chosen_by = "kept"
            notes.append(
                "The current classifier no longer matches this dataset to a domain template, so the "
                f"existing {current.label} classification was kept instead of being downgraded."
            )

    decisions = suggest_mapping(work, profile, schema)
    overrides = _preserve_manual_mappings(schema, stored_decisions, set(work.columns), review)
    if overrides:
        _apply_manual_decisions(decisions, overrides, work, profile, schema)
    mapping = _dedupe_mapping(
        schema, _drop_derived_sources(schema, _canonical_mapping(decisions), decisions), decisions, review
    )

    # ── Target & task ────────────────────────────────────────────────────────
    stored_target = (meta.target_field or "").strip()
    target: Optional[str] = None
    task = "eda"
    if stored_target:
        key = _target_key(schema, mapping, work, stored_target)
        if key:
            target = key
            task = meta.analysis_task or "eda"
            notes.append(
                f"Your confirmed target '{stored_target}' was kept as '{key}' "
                f"({task})."
            )
        else:
            review.append({
                "kind": "target_dropped",
                "field": stored_target,
                "message": (
                    f"Your confirmed target '{stored_target}' is not part of the {schema.label} template "
                    "and could not be carried over. Choose a target again in the Analysis Report."
                ),
            })
    if target is None:
        suggested = classification.get("detected_target")
        if suggested:
            notes.append(
                f"'{suggested}' looks like an outcome column; confirm it as the target in the Analysis "
                "Report to run a supervised model. Nothing is trained until you confirm."
            )

    validation = validate_dataset(work, profile, schema, mapping, task, target)
    if not validation.get("ready"):
        failing = [check for check in validation.get("checks", []) if check.get("status") == "fail"]
        raise ReclassifyError(
            f"The data stored for this dataset does not satisfy the {schema.label} template, "
            "so the classification was left unchanged.",
            status_code=409,
            details={
                "schema": schema.id,
                "schema_label": schema.label,
                "validation": validation,
                "failing": failing,
                "review": review,
            },
        )

    records, _generated, skipped = build_records(work, schema, mapping)
    if not records:
        raise ReclassifyError(
            "No usable rows would remain with this template, so the classification was left unchanged.",
            status_code=409,
            details={"schema": schema.id, "validation": validation},
        )
    fingerprint = _records_fingerprint(records)

    mapping_changed = mapping != stored_canonical
    schema_changed = schema.id != current.id
    # The stored rows already are exactly what this template produces (the hash
    # covers every canonical value), so nothing needs rewriting.
    rows_identical = bool(stored_fingerprint) and stored_fingerprint == fingerprint
    same_setup = (
        rows_identical
        and not schema_changed
        and task == (meta.analysis_task or "eda")
        and target == (meta.target_field or None)
    )
    if same_setup:
        return {
            "success": True,
            "changed": False,
            "status": "unchanged",
            "message": (
                f"'{meta.dataset_name}' already matches the current classifier "
                f"({schema.label}). Nothing was rewritten."
            ),
            "dataset": dataset_payload(meta),
            "before": before,
            "after": before,
            "review": [],
            "notes": ["Re-running reclassification is safe: stored rows were not touched."],
            "mapping_changes": [],
            "rows_rewritten": 0,
        }

    rebuild_rows = not rows_identical
    status = "reclassified" if schema_changed else (
        "remapped" if (mapping_changed and rebuild_rows) else "refreshed"
    )
    if not rebuild_rows:
        notes.append(
            "The stored rows already match this mapping, so they were kept as they are and only the "
            "dataset metadata was refreshed."
        )

    sales_total = 0.0
    if schema.id == "sales":
        sales_total = round(sum(float(record.get("sales") or 0) for record in records), 2)
    elif schema.id == "churn":
        sales_total = round(sum(
            float(record.get("total_charge") or record.get("total_charge_derived") or 0)
            for record in records
        ), 2)
    row_count = len(records)
    customer_count = len({
        str(record.get("customer_id") or record.get("subscriber_id"))
        for record in records
        if record.get("customer_id") or record.get("subscriber_id")
    })

    modules = modules_supported(schema.id, validation["capabilities"], validation["forecast"])
    classified_at = datetime.utcnow().isoformat()
    classification_meta = {
        "confidence": classification.get("confidence"),
        "ambiguous": classification.get("ambiguous"),
        "chosen_by": chosen_by,
        "reasons": classification.get("reasons", []),
        "alternatives": classification.get("alternatives", []),
        "detected_target": classification.get("detected_target"),
        "target_candidates": classification.get("targets", []),
        "supported_tasks": classification.get("supported_tasks", {}),
        "classified_at": classified_at,
        "previous_schema": before["schema"],
        "records_fingerprint": fingerprint,
    }
    if classification.get("ambiguous") and chosen_by != "kept":
        review.append({
            "kind": "low_confidence",
            "message": (
                f"The {schema.label} template matched with low confidence "
                f"({classification.get('confidence') or 0}%). Review the mapping before relying on it."
            ),
        })
    if target is None:
        review.append({
            "kind": "target_unset",
            "message": "No supervised target is confirmed, so classification/regression stay off until you pick one.",
        })

    try:
        if rebuild_rows:
            db.query(DatasetRow).filter(
                DatasetRow.owner_id == owner_id, DatasetRow.dataset_id == meta.id
            ).delete(synchronize_session=False)
            db.flush()
            for start in range(0, len(records), 2000):
                db.bulk_insert_mappings(
                    DatasetRow,
                    [
                        {
                            "owner_id": owner_id,
                            "dataset_id": meta.id,
                            "row_index": start + offset + 1,
                            "payload": record,
                        }
                        for offset, record in enumerate(records[start:start + 2000])
                    ],
                )

        meta.dataset_type = schema.id
        meta.schema_kind = schema.id
        meta.analysis_task = task
        meta.target_field = target
        meta.row_count = row_count
        meta.customer_count = customer_count
        meta.total_sales = sales_total
        # Keep the original profile/mapping when nothing about the dataset
        # changed: they describe the source columns of the stored rows, which
        # the canonical-frame re-run cannot reproduce.
        if schema_changed or not stored_profile_json:
            meta.profile_json = json.dumps(profile, default=str)
        # Only a rebuild makes the previously stored mapping stale; otherwise the
        # existing mapping still describes the stored rows (and keeps the original
        # source column names rather than the canonical ones).
        if (rebuild_rows and mapping_changed) or not stored_mapping_json:
            meta.mapping_json = json.dumps(decisions, default=str)
        if schema_changed:
            meta.schema_json = json.dumps(schema.to_payload(), default=str)
        meta.validation_json = json.dumps(
            {
                "ready": validation.get("ready"),
                "errors": validation.get("errors"),
                "warnings": validation.get("warnings"),
                "checks": validation.get("checks", []),
                "forecast": validation.get("forecast"),
                "notes": _notes_for(schema, validation, target, task),
                "skipped_rows": skipped,
                "reclassified_at": classified_at,
            },
            default=str,
        )
        # Keep the previous capability map until the new frame is committed, but
        # record the classifier's own verdict now (it is what idempotency uses).
        previous_caps = _loads(meta.capabilities_json, {}) or {}
        meta.capabilities_json = json.dumps(
            {
                **{key: value for key, value in previous_caps.items() if key != "modules"},
                "modules": previous_caps.get("modules", {}),
                "modules_supported": modules,
                "classification": classification_meta,
            },
            default=str,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    # Capabilities and native tables are recomputed from the committed rows.
    rebuild_warning = None
    try:
        capabilities, _frame = build_capabilities(db, owner_id, meta)
        capabilities["classification"] = classification_meta
        capabilities["modules_supported"] = modules
        meta.capabilities_json = json.dumps(capabilities, default=str)
        db.commit()
        if meta.is_active:
            meta = set_active(db, owner_id, meta.id) or meta
    except Exception as exc:  # pragma: no cover - defensive, reported to the client
        db.rollback()
        rebuild_warning = (
            "The classification was saved, but the analytics tables could not be rebuilt "
            f"({exc}). Activate the dataset again to retry."
        )

    after_caps = _loads(meta.capabilities_json, {}) or {}
    after = {
        "schema": meta.schema_kind,
        "schema_label": get_schema(meta.schema_kind).label,
        "task": meta.analysis_task,
        "target": meta.target_field,
        "rows": meta.row_count or 0,
        "confidence": (after_caps.get("classification") or {}).get("confidence"),
        "modules": _module_statuses(after_caps),
        "uploaded_at": before["uploaded_at"],
    }

    if rebuild_warning:
        notes.append(rebuild_warning)
    if skipped:
        notes.append(f"{skipped:,} rows were skipped because a required field had no usable value.")

    return {
        "success": True,
        "changed": True,
        "status": status,
        "message": (
            f"'{meta.dataset_name}' is now analysed as {after['schema_label']}."
            if status == "reclassified"
            else (
                f"'{meta.dataset_name}' kept its template but its column mapping was refreshed."
                if status == "remapped"
                else f"'{meta.dataset_name}' already matched the current classifier; only its metadata was refreshed."
            )
        ),
        "dataset": dataset_payload(meta),
        "before": before,
        "after": after,
        "classification": classification_meta,
        "mapping": [
            {
                "field": key,
                "label": decision.get("label") or key,
                "column": decision.get("column"),
                "status": decision.get("status"),
                "confidence": decision.get("confidence"),
                "required": bool(decision.get("required")),
                "reasons": decision.get("reasons", []),
            }
            for key, decision in ((spec.key, decisions.get(spec.key, {})) for spec in schema.fields)
        ],
        "mapping_changes": _mapping_diff(stored_canonical, mapping, decisions),
        "validation": {
            "ready": validation.get("ready"),
            "errors": validation.get("errors"),
            "warnings": validation.get("warnings"),
            "checks": validation.get("checks", []),
        },
        "tasks": classification.get("supported_tasks", {}),
        "review": review,
        "notes": notes,
        "rows_rewritten": len(records),
        "source": source_kind,
    }
