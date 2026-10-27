"""
Dataset upload and ingestion.

  POST /api/upload/preview  — profile + classify + suggest mapping + validate
  POST /api/upload/validate — re-validate an edited mapping server-side
  POST /api/upload/commit   — validate again, then ingest and register
  GET  /api/upload/status   — active dataset + module availability
  GET  /api/upload/templates— supported analysis schemas

No value is fabricated: required fields must come from the file (or a labelled
technical row index for identifiers), and derived fields only exist when their
declared formula has real inputs.
"""
from __future__ import annotations

import io
import json
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import DatasetRow
from security import require_user
from services.classifier import classify_dataset, detect_targets, resolve_task
from services.ingestion import active_dataset, create_dataset, dataset_payload
from services.mapping import DERIVED, GENERATE, UNMAPPED, suggest_mapping
from services.profiling import profile_dataframe
from services.schemas import CUSTOM, SCHEMAS, DatasetSchema, get_schema
from services.validation import validate_dataset, modules_supported

router = APIRouter()

MAX_FILE_BYTES = 40 * 1024 * 1024
ALLOWED_EXTENSIONS = (".csv", ".txt", ".xlsx", ".xls")
PREVIEW_ROWS = 6


def _read_file(contents: bytes, filename: str) -> pd.DataFrame:
    lowered = (filename or "").lower()
    if not lowered.endswith(ALLOWED_EXTENSIONS):
        raise ValueError("Only CSV and Excel files (.csv, .xlsx, .xls) are supported.")
    if not contents:
        raise ValueError("The uploaded file is empty.")
    if len(contents) > MAX_FILE_BYTES:
        raise ValueError(f"File is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")

    if lowered.endswith((".xlsx", ".xls")):
        try:
            return pd.read_excel(io.BytesIO(contents))
        except Exception as exc:
            raise ValueError(f"Could not read the Excel workbook: {exc}") from exc

    last_error: Optional[Exception] = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            frame = pd.read_csv(io.BytesIO(contents), encoding=encoding, sep=None, engine="python")
            if frame.empty and not len(frame.columns):
                raise ValueError("The file has no readable columns.")
            return frame
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        except Exception as exc:
            raise ValueError(f"Could not parse the CSV file: {exc}") from exc
    raise ValueError(f"Could not decode the file as text: {last_error}")


def _limit_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, Optional[int]]:
    if len(df) > 200_000:
        return df.head(200_000), int(len(df) - 200_000)
    return df, None


def _preview_payload(df: pd.DataFrame, limit_hit: Optional[int]) -> list[dict]:
    return [
        {
            str(column): ("" if pd.isna(value) else str(value))[:200]
            for column, value in row.items()
        }
        for row in df.head(PREVIEW_ROWS).to_dict(orient="records")
    ]


def _canonical_mapping(decisions: dict[str, dict], overrides: dict[str, str]) -> dict[str, str]:
    """Merge the user's overrides into the suggested mapping."""
    mapping: dict[str, str] = {}
    for key, decision in decisions.items():
        if decision["status"] == "derived":
            mapping[key] = DERIVED
        elif decision.get("value") == GENERATE:
            mapping[key] = GENERATE
        elif decision.get("column"):
            mapping[key] = decision["column"]

    for key, value in overrides.items():
        if value is None:
            value = ""
        mapping[key] = value
    return mapping


def _decorate_decisions(
    decisions: dict[str, dict],
    overrides: dict[str, str],
    df: pd.DataFrame,
    profile: dict,
) -> dict[str, dict]:
    """Mark fields the user changed as manual and refresh their explanation."""
    from services.mapping import score_field
    from services.schemas import FieldSpec

    columns = {column["name"]: column for column in profile["column_profiles"]}
    for key, decision in decisions.items():
        if key not in overrides:
            continue
        value = overrides.get(key) or ""
        if value == DERIVED and decision["status"] == "derived":
            continue
        if value == GENERATE:
            decision.update({
                "value": GENERATE,
                "column": None,
                "status": "generated",
                "confidence": "generated",
                "reasons": ["user chose to generate a technical row index"],
            })
            continue
        if value in ("", UNMAPPED):
            decision.update({
                "value": UNMAPPED,
                "column": None,
                "status": "unmapped",
                "confidence": "none",
                "reasons": ["cleared by the user"],
                "score": 0.0,
            })
            continue
        if value in df.columns and value in columns:
            spec = FieldSpec(
                key=decision["field"],
                label=decision["label"],
                description=decision.get("description", ""),
                dtype=decision.get("dtype", "text"),
                required=bool(decision.get("required")),
                target=bool(decision.get("target")),
                role=decision.get("role", "feature"),
            )
            scored = score_field(spec, value, columns[value], df)
            decision.update({
                "value": value,
                "column": value,
                "status": "manual",
                "confidence": "manual",
                "score": scored["score"],
                "reasons": ["selected by the user"] + scored["reasons"],
                "sample_values": columns[value].get("sample_values", []),
                "source_dtype": columns[value]["dtype"],
            })
    return decisions


def _resolve_target_key(
    schema: DatasetSchema,
    mapping: dict[str, str],
    df: pd.DataFrame,
    profile: dict,
    requested: Optional[str],
    task: str,
) -> Optional[str]:
    """Map a requested target to the canonical record key used by the engine."""

    def canonical(column: str) -> Optional[str]:
        if schema.field(column):
            return column
        if column in df.columns:
            for key, mapped_column in mapping.items():
                if mapped_column == column and (schema.field(key) or schema.custom):
                    return key
            if schema.custom or schema.id == "generic" or not schema.fields:
                return column
        return None

    if task == "clustering":
        return None

    if requested:
        if requested == "__none__":
            return None
        return canonical(requested)

    if task == "forecast":
        target_spec = schema.field(schema.default_target or "") or next(
            (spec for spec in schema.fields if spec.target), None
        )
        return target_spec.key if target_spec else None

    candidates = [
        candidate for candidate in detect_targets(profile)
        if candidate["task"] == task
    ]
    if candidates:
        return canonical(candidates[0]["column"])
    return None


def _build_preview(
    df: pd.DataFrame,
    filename: str,
    requested_schema: str,
    overrides: dict[str, str],
    requested_task: Optional[str],
    requested_target: Optional[str],
) -> dict:
    profile = profile_dataframe(df)
    classification = classify_dataset(df, profile)

    if requested_schema and requested_schema not in ("auto", ""):
        schema = get_schema(requested_schema)
        decisions = suggest_mapping(df, profile, schema)
    else:
        schema = get_schema(classification["schema"])
        decisions = classification.get("mapping") or suggest_mapping(df, profile, schema)

    mapping = _canonical_mapping(decisions, overrides)
    decisions = _decorate_decisions(decisions, overrides, df, profile)

    resolved = resolve_task(schema, profile, requested_task, requested_target)
    task = resolved["task"]
    target = _resolve_target_key(schema, mapping, df, profile, requested_target, task)
    if task in ("classification", "regression") and not target:
        task = "eda"

    validation = validate_dataset(df, profile, schema, mapping, task, target)
    modules = modules_supported(schema.id, validation["capabilities"], validation["forecast"])

    return {
        "filename": filename,
        "total_rows": int(len(df)),
        "columns": [str(column) for column in df.columns],
        "preview": _preview_payload(df, None),
        "profile": profile,
        "classification": {
            key: value for key, value in classification.items()
            if key != "mapping"
        },
        "schema": schema.to_payload(),
        "analysis_type": schema.id,
        "mapping": decisions,
        "task": task,
        "target": target,
        "tasks": resolved["supported_tasks"],
        "targets": resolved["target_candidates"],
        "validation": validation,
        "modules": modules,
    }


@router.get("/templates")
def get_templates():
    """Supported analysis templates with their target fields."""
    return {
        "templates": [schema.to_payload() for schema in SCHEMAS.values() if schema.id != CUSTOM.id],
        "limit_rows": 200_000,
        "max_file_mb": MAX_FILE_BYTES // (1024 * 1024),
    }


@router.post("/preview")
async def preview_upload(
    file: UploadFile = File(...),
    analysis_type: str = Query("auto"),
    mapping: str = Form(default=""),
    task: str = Form(default=""),
    target: str = Form(default=""),
):
    """Profile the file, classify it, and suggest an explainable mapping."""
    try:
        contents = await file.read()
        df = _read_file(contents, file.filename or "upload.csv")
        df, truncated = _limit_rows(df)
        overrides = json.loads(mapping) if mapping else {}
        payload = _build_preview(
            df,
            file.filename or "upload.csv",
            analysis_type,
            overrides,
            task or None,
            target or None,
        )
        if truncated:
            payload["validation"]["checks"].insert(0, {
                "id": "row_limit",
                "label": "Row limit",
                "status": "warn",
                "detail": f"Only the first 200,000 rows are analysed; {truncated:,} rows were ignored.",
                "field": None,
                "rows": truncated,
            })
        return payload
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read file: {exc}") from exc


@router.post("/validate")
async def validate_upload(
    file: UploadFile = File(...),
    schema_id: str = Form(default="generic", alias="schema"),
    mapping: str = Form(default="{}"),
    task: str = Form(default="eda"),
    target: str = Form(default=""),
):
    """Re-run validation for an edited mapping (server-side authority)."""
    try:
        contents = await file.read()
        df = _read_file(contents, file.filename or "upload.csv")
        df, _ = _limit_rows(df)
        profile = profile_dataframe(df)
        dataset_schema = get_schema(schema_id)
        mapping_dict = json.loads(mapping or "{}")
        decisions = suggest_mapping(df, profile, dataset_schema)
        canonical = _canonical_mapping(decisions, mapping_dict)
        resolved_target = _resolve_target_key(
            dataset_schema, canonical, df, profile, target or None, task or "eda"
        )
        validation = validate_dataset(
            df, profile, dataset_schema, canonical, task or "eda", resolved_target
        )
        return {
            "validation": validation,
            "task": task or "eda",
            "target": resolved_target,
            "modules": modules_supported(
                dataset_schema.id, validation["capabilities"], validation["forecast"]
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/commit")
async def commit_upload(
    file: UploadFile = File(...),
    schema_id: str = Form(default="generic", alias="schema"),
    mapping: str = Form(default="{}"),
    org_name: str = Form(default=""),
    task: str = Form(default="eda"),
    target: str = Form(default=""),
    db: Session = Depends(get_db),
    owner: str = Depends(require_user),
):
    """Validate the final mapping server-side, then ingest and register."""
    try:
        contents = await file.read()
        df = _read_file(contents, file.filename or "upload.csv")
        df, truncated = _limit_rows(df)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    profile = profile_dataframe(df)
    dataset_schema = get_schema(schema_id)
    overrides = json.loads(mapping or "{}")
    decisions = suggest_mapping(df, profile, dataset_schema)
    canonical = _canonical_mapping(decisions, overrides)
    decisions = _decorate_decisions(decisions, overrides, df, profile)
    resolved_target = _resolve_target_key(
        dataset_schema, canonical, df, profile, target or None, task or "eda"
    )
    validation = validate_dataset(
        df, profile, dataset_schema, canonical, task or "eda", resolved_target
    )

    if not validation["ready"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Validation failed. Fix the errors before loading this dataset.",
                "validation": validation,
            },
        )

    modules = modules_supported(dataset_schema.id, validation["capabilities"], validation["forecast"])
    try:
        meta = create_dataset(
            db=db,
            owner_id=owner,
            df=df,
            filename=file.filename or "upload.csv",
            org_name=org_name,
            schema=dataset_schema,
            mapping=canonical,
            decisions=decisions,
            task=task or "eda",
            target=resolved_target,
            profile=profile,
            validation=validation,
            capabilities=validation["capabilities"],
            modules=modules,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}") from exc

    skipped = 0
    try:
        skipped = int(json.loads(meta.validation_json or "{}").get("skipped_rows", 0))
    except (TypeError, ValueError):
        skipped = 0

    return {
        "success": True,
        "dataset": dataset_payload(meta),
        "rows_loaded": meta.row_count,
        "rows_skipped": skipped,
        "rows_ignored": truncated or 0,
        "schema": dataset_schema.id,
        "schema_label": dataset_schema.label,
        "task": meta.analysis_task,
        "target": meta.target_field,
        "warnings": validation["warnings"],
        "modules": modules,
        "message": (
            f"Loaded {meta.row_count:,} {dataset_schema.label.lower()} records"
            + (f", skipped {skipped:,} rows with unusable required values" if skipped else "")
            + "."
        ),
    }


@router.get("/status")
def get_upload_status(
    db: Session = Depends(get_db),
    owner: str = Depends(require_user),
):
    """Active dataset, its capabilities and which modules can run."""
    meta = active_dataset(db, owner)
    if meta is None:
        return {
            "has_data": False,
            "dataset": None,
            "dataset_count": 0,
            "modules": {},
            "capabilities": {},
        }

    payload = dataset_payload(meta)
    capabilities = payload.get("capabilities", {})
    if "understanding" not in capabilities:
        # Older uploads stored the template-level boolean map. Recompute the
        # data-derived capabilities once, then keep them on the dataset.
        from services.capabilities import build_capabilities

        capabilities, _ = build_capabilities(db, owner, meta)
        meta.capabilities_json = json.dumps(capabilities, default=str)
        db.commit()

    raw_modules = capabilities.get("modules") or {}
    modules = {
        name: (info.get("status") != "unavailable" if isinstance(info, dict) else bool(info))
        for name, info in raw_modules.items()
    }
    modules.setdefault("adaptive_report", meta.schema_kind != "sales")
    count = db.query(DatasetRow.dataset_id).filter(DatasetRow.owner_id == owner).distinct().count()
    validation = payload.get("validation", {})

    return {
        "has_data": True,
        "dataset": payload,
        "dataset_count": count,
        "dataset_name": meta.dataset_name,
        "org_name": meta.org_name,
        "schema": meta.schema_kind,
        "schema_label": payload.get("schema_label"),
        "task": meta.analysis_task,
        "target": meta.target_field,
        "row_count": meta.row_count,
        "customer_count": meta.customer_count,
        "total_sales": meta.total_sales,
        "date_range": {
            "from": (validation.get("forecast") or {}).get("from"),
            "to": (validation.get("forecast") or {}).get("to"),
        },
        "capabilities": capabilities,
        "modules": modules,
        "notes": validation.get("notes", []),
    }
