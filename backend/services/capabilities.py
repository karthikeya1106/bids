"""
Dataset capability registry.

The analytics modules used to gate on the dataset *label*: anything that was not
``sales`` was rejected with a sales-only explanation. That is wrong for a churn,
HR or generic table that still has a real outcome column and real measures.

Capabilities are now derived from the committed data itself — column roles, the
observed target, row counts, time coverage and quality — and each module gets an
honest status: ``ready``, ``partial`` (some analyses supported) or
``unavailable`` with the requirements it is missing.

Nothing here invents data. A target is only *suggested* from its values and name
until the user confirms it; supervised modelling requires that confirmation.
"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd
from sqlalchemy.orm import Session

from db.models import DatasetMeta
from services import cache
from services.ingestion import active_dataset, records_frame
from services.profiling import coerce_numeric, detect_frequency
from services.schemas import get_schema
from services.semantics import humanize, looks_like_id, looks_like_measure

# Names that usually denote an outcome rather than an input. Matched on
# normalised (lowercase, underscore-separated) column names.
TARGET_SIGNALS = (
    "churn", "churned", "churning", "attrition", "attrited", "exited",
    "cancel", "cancelled", "canceled", "cancellation", "left", "resigned",
    "terminated", "defected", "unsubscribed", "converted", "fraud",
    "is_fraud", "defaulted", "default", "is_active", "isactive", "retained",
    "survived", "target", "label", "outcome", "subscribed",
)

# Values that mean "the customer left / the event happened".
EVENT_LABELS = {
    "1", "true", "t", "yes", "y", "churned", "churn", "left", "exited",
    "cancelled", "canceled", "attrition", "defaulted", "fraud", "unsubscribed",
    "resigned", "terminated", "inactive", "0",  # 0 only when the name says is_active
}
RETENTION_LABELS = {"0", "false", "f", "no", "n", "active", "retained", "stayed", "current"}

MONEY_HINTS = ("bill", "charge", "revenue", "sales", "amount", "price", "spend", "cost", "income", "profit", "value")
TENURE_HINTS = ("tenure", "subscription_age", "account_age", "age", "lifetime", "months")
USAGE_HINTS = ("download", "upload", "usage", "minutes", "mins", "calls", "messages", "data")

MIN_ROWS = 30
MIN_MODEL_ROWS = 60


# ─── Frame preparation ────────────────────────────────────────────────────────

def load_frame(db: Session, owner_id: str, meta: DatasetMeta) -> pd.DataFrame:
    """Committed canonical rows for one dataset (all original columns)."""
    frame = records_frame(db, owner_id, meta.id)
    if frame.empty and meta.schema_kind == "sales":
        # Legacy seeded workspaces have native order rows but no stored records.
        from services.analytics import load_orders_df

        frame = load_orders_df(db, owner_id)
    return frame


def prepare_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Coerce numeric/date-like text columns so analytics see real types."""
    work = frame.copy()
    work = work.drop(columns=["__row__"], errors="ignore")
    for column in work.columns:
        series = work[column]
        if series.dtype != object:
            continue
        numeric = coerce_numeric(series)
        if numeric.notna().mean() >= 0.9:
            work[column] = numeric
            continue
        text = series.astype(str)
        if text.str.contains(r"[-/:T]").mean() >= 0.8:
            parsed = pd.to_datetime(series, errors="coerce", format="mixed")
            if parsed.notna().mean() >= 0.85:
                work[column] = parsed
    return work


def _unique_ratio(series: pd.Series) -> float:
    non_null = series.dropna()
    return float(non_null.nunique() / len(non_null)) if len(non_null) else 0.0


def column_roles(frame: pd.DataFrame) -> dict[str, Any]:
    """Classify every column by what it can legitimately be used for."""
    roles: dict[str, list[str]] = {
        "identifiers": [], "datetime": [], "measures": [],
        "binary": [], "categorical": [], "text": [],
    }
    details: list[dict] = []

    for column in frame.columns:
        series = frame[column]
        non_null = series.dropna()
        unique = int(non_null.nunique())
        missing_pct = round(float(series.isna().mean() * 100), 2) if len(series) else 0.0
        ratio = _unique_ratio(series)

        is_numeric = pd.api.types.is_numeric_dtype(series)
        if pd.api.types.is_datetime64_any_dtype(series):
            kind = "datetime"
        elif pd.api.types.is_bool_dtype(series):
            kind = "binary"
        elif looks_like_id(str(column)) or (not is_numeric and unique > 20 and ratio >= 0.98):
            # A numeric column with every value distinct is usually a measure
            # (revenue, price, age), not an identifier. Only names and text
            # columns get the uniqueness shortcut.
            kind = "identifier"
        elif pd.api.types.is_numeric_dtype(series):
            if unique <= 2:
                kind = "binary"
            elif unique <= 10 and (non_null % 1 == 0).all():
                kind = "categorical"  # ordinal codes / counts with few levels
            else:
                kind = "measure"
        elif unique <= 2:
            kind = "binary"
        elif unique <= 30 and ratio < 0.6:
            kind = "categorical"
        else:
            kind = "text"

        bucket = {
            "identifier": "identifiers", "datetime": "datetime", "measure": "measures",
            "binary": "binary", "categorical": "categorical", "text": "text",
        }[kind]
        roles[bucket].append(str(column))
        details.append({
            "name": str(column),
            "kind": kind,
            "unique": unique,
            "unique_ratio": round(ratio, 4),
            "missing_pct": missing_pct,
            "label": humanize(str(column)),
            "measure_hint": looks_like_measure(str(column)),
        })
    return {"roles": roles, "columns": details}


# ─── Target detection ────────────────────────────────────────────────────────

def _labels(series: pd.Series) -> tuple[list[str], list[int]]:
    counts = series.dropna().astype(str).str.strip().value_counts()
    labels = [str(value) for value in counts.index.tolist()]
    return labels, [int(value) for value in counts.tolist()]


def _event_label(column: str, labels: list[str]) -> Optional[str]:
    normal = str(column).lower()
    if normal in {"is_active", "isactive", "retained", "survived"}:
        # Inverted flag: 0/No means the customer is gone.
        for label in labels:
            if label.lower() in {"0", "false", "no", "n", "inactive"}:
                return label
        return None
    for label in labels:
        if label.lower() in {"churned", "churn", "left", "exited", "cancelled", "canceled", "attrition", "1", "true", "yes"}:
            return label
    for label in labels:
        if label.lower() in EVENT_LABELS:
            return label
    return None


def detect_targets(roles: dict[str, Any], frame: pd.DataFrame) -> list[dict]:
    """Candidate supervised targets with the evidence for suggesting them."""
    candidates: list[dict] = []
    measures = set(roles["roles"]["measures"])
    identifiers = set(roles["roles"]["identifiers"])

    for column in frame.columns:
        name = str(column)
        if name in identifiers:
            continue
        series = frame[column]
        non_null = series.dropna()
        if non_null.empty:
            continue
        unique = int(non_null.nunique())
        missing_pct = float(series.isna().mean() * 100)
        if missing_pct >= 60:
            continue
        normal = name.lower()
        signal = next((word for word in TARGET_SIGNALS if word in normal), None)

        if 2 <= unique <= 20 and not pd.api.types.is_datetime64_any_dtype(series):
            labels, counts = _labels(series)
            minority = min(counts) / max(1, sum(counts))
            candidates.append({
                "column": name,
                "kind": "binary" if unique == 2 else "multiclass",
                "task": "classification",
                "classes": unique,
                "missing_pct": round(missing_pct, 2),
                "minority_share": round(minority * 100, 2),
                "reason": (
                    f"column name contains '{signal}' and has {unique} observed outcomes"
                    if signal
                    else f"{unique} observed outcomes; {minority * 100:.1f}% in the smallest class"
                ),
                "priority": 1 if signal else (2 if unique == 2 else 4),
                "suggested": bool(signal),
            })
            continue

        if name in measures and unique > 10:
            measure_signal = next(
                (word for word in ("revenue", "sales", "charges", "bill", "amount", "profit", "score", "demand") if word in normal),
                None,
            )
            candidates.append({
                "column": name,
                "kind": "continuous",
                "task": "regression",
                "classes": None,
                "missing_pct": round(missing_pct, 2),
                "minority_share": None,
                "reason": (
                    f"continuous measure ('{measure_signal}') with {unique:,} distinct values"
                    if measure_signal else f"continuous column with {unique:,} distinct values"
                ),
                "priority": 3 if measure_signal else 5,
                "suggested": False,
            })

    deduped: dict[str, dict] = {}
    for candidate in candidates:
        current = deduped.get(candidate["column"])
        if current is None or candidate["priority"] < current["priority"]:
            deduped[candidate["column"]] = candidate
    return sorted(deduped.values(), key=lambda item: (item["priority"], item["column"]))[:6]


def resolve_target(meta: DatasetMeta, frame: pd.DataFrame, roles: dict[str, Any]) -> tuple[Optional[dict], list[dict]]:
    """Return the target in use (confirmed or suggested) plus all suggestions."""
    suggestions = detect_targets(roles, frame)
    confirmed_column = (meta.target_field or "").strip()
    if confirmed_column and confirmed_column in frame.columns:
        series = frame[confirmed_column].dropna()
        unique = int(series.nunique())
        labels, counts = _labels(series)
        total = max(1, sum(counts))
        event = _event_label(confirmed_column, labels) if unique <= 20 else None
        return (
            {
                "column": confirmed_column,
                "kind": "binary" if unique == 2 else ("multiclass" if unique <= 20 else "continuous"),
                "task": meta.analysis_task if meta.analysis_task in {"classification", "regression"} else ("classification" if unique <= 20 else "regression"),
                "classes": [
                    {"label": label, "count": count, "share": round(count / total * 100, 2)}
                    for label, count in zip(labels, counts)
                ],
                "event": event,
                "event_share": (
                    round(next(count for label, count in zip(labels, counts) if label == event) / total * 100, 2)
                    if event else None
                ),
                "confirmed": True,
                "reasons": [f"confirmed by the user for {meta.analysis_task or 'analysis'}"],
            },
            suggestions,
        )

    suggested = next((candidate for candidate in suggestions if candidate["suggested"]), None)
    if suggested is None:
        return None, suggestions
    series = frame[suggested["column"]].dropna()
    labels, counts = _labels(series)
    total = max(1, sum(counts))
    event = _event_label(suggested["column"], labels)
    return (
        {
            "column": suggested["column"],
            "kind": suggested["kind"],
            "task": suggested["task"],
            "classes": [
                {"label": label, "count": count, "share": round(count / total * 100, 2)}
                for label, count in zip(labels, counts)
            ],
            "event": event,
            "event_share": (
                round(next(count for label, count in zip(labels, counts) if label == event) / total * 100, 2)
                if event else None
            ),
            "confirmed": False,
            "reasons": [
                suggested["reason"],
                "suggested from the observed values; confirm it before supervised modelling",
            ],
        },
        suggestions,
    )


# ─── Capabilities ────────────────────────────────────────────────────────────

def _module(status: str, reasons: list[str], requires: Optional[list[str]] = None, **extra: Any) -> dict:
    return {"status": status, "reasons": reasons, "requires": requires or [], **extra}


def build_capabilities(
    db: Session,
    owner_id: str,
    meta: Optional[DatasetMeta] = None,
    reference: Optional[pd.DataFrame] = None,
) -> tuple[dict, pd.DataFrame]:
    """Compute what the active dataset can support, from the data itself."""
    meta = meta or active_dataset(db, owner_id)
    if meta is None:
        empty = pd.DataFrame()
        capabilities = {
            "mode": "empty",
            "dataset": None,
            "roles": {"identifiers": [], "datetime": [], "measures": [], "binary": [], "categorical": [], "text": []},
            "columns": [],
            "target": None,
            "target_suggestions": [],
            "has_time": False,
            "time_coverage": None,
            "modules": {
                module: _module("unavailable", ["No dataset is registered for this workspace."], ["Upload a dataset"])
                for module in ("dashboard", "behavior", "segmentation", "rootcause", "drift", "forecast", "strategy", "analysis")
            },
        }
        return capabilities, empty

    cache_key = cache.dataset_signature(meta) if reference is None else None
    cached = cache.get_frame(cache_key)
    if cached is not None:
        return cached

    raw = load_frame(db, owner_id, meta)
    frame = prepare_frame(raw) if not raw.empty else raw
    rows = int(len(frame))
    roles = column_roles(frame) if rows else {"roles": {key: [] for key in ("identifiers", "datetime", "measures", "binary", "categorical", "text")}, "columns": []}
    target, suggestions = resolve_target(meta, frame, roles)

    time_columns = roles["roles"]["datetime"]
    time_coverage = detect_frequency(frame[time_columns[0]]) if time_columns else None
    if time_coverage:
        time_coverage = {"column": time_columns[0], **time_coverage}
    measures = roles["roles"]["measures"]
    dimensions = roles["roles"]["binary"] + roles["roles"]["categorical"]
    identifiers = roles["roles"]["identifiers"]
    schema_id = meta.schema_kind or "generic"
    schema = get_schema(schema_id)

    target_classes = len(target["classes"]) if target else 0
    target_ready = bool(target and target_classes >= 2 and target["kind"] in {"binary", "multiclass"})
    supervised_ready = bool(target_ready and target and target["confirmed"] and rows >= MIN_MODEL_ROWS)
    time_series_ready = bool(time_coverage and measures and time_coverage.get("periods", 0) >= 3 and rows >= 12)

    subject_count = int(frame[identifiers[0]].nunique()) if identifiers else rows
    subject_label = "customers" if schema_id in {"churn", "sales"} else "records"

    modules: dict[str, dict] = {}

    modules["dashboard"] = _module(
        "ready" if rows else "unavailable",
        [
            f"{rows:,} committed rows across {len(frame.columns)} columns",
            f"{subject_count:,} distinct {subject_label}",
            (
                f"observed outcome '{target['column']}' with {target_classes} classes"
                if target else "no outcome column was detected"
            ),
        ],
        [] if rows else ["Upload a dataset"],
        kpis=True,
    )

    if rows >= MIN_ROWS and (target_ready or dimensions):
        modules["behavior"] = _module(
            "ready",
            [
                f"compares {len(measures)} numeric measures and {len(dimensions)} grouping columns",
                (
                    f"uses the observed outcome '{target['column']}' for outcome splits"
                    if target_ready else "no outcome column; descriptive profiles only"
                ),
            ],
        )
    else:
        modules["behavior"] = _module(
            "unavailable",
            [f"needs at least {MIN_ROWS} rows and either an outcome or grouping columns"],
            ["A dataset with at least 30 rows"],
        )

    if rows >= MIN_ROWS and len(measures) >= 2:
        modules["segmentation"] = _module(
            "ready",
            [
                f"clusters on {min(len(measures), 10)} numeric features",
                f"{rows:,} rows available for K-means",
            ],
        )
    else:
        modules["segmentation"] = _module(
            "unavailable",
            [f"needs at least {MIN_ROWS} rows and 2 numeric columns"],
            ["At least two numeric columns"],
        )

    if target_ready and rows >= MIN_ROWS:
        modules["rootcause"] = _module(
            "ready",
            [
                f"tests associations between '{target['column']}' and {len(measures)} measures / {len(dimensions)} groups",
                "reports effect sizes and p-values; association is not causation",
            ],
        )
    elif time_series_ready:
        modules["rootcause"] = _module(
            "ready",
            [f"no outcome column; analyses the {time_coverage['frequency']} trend of mapped measures"],
        )
    else:
        modules["rootcause"] = _module(
            "unavailable",
            ["needs an outcome column with 2-20 classes, or a date column with a numeric measure"],
            ["A churn/attrition-style outcome column or a date column"],
        )

    if reference is not None and not reference.empty:
        modules["drift"] = _module(
            "ready",
            [f"compares the active dataset with the selected reference ({len(reference):,} rows)"],
            drift_mode="reference",
        )
    elif time_series_ready:
        modules["drift"] = _module(
            "ready",
            [f"compares earlier and later periods of '{time_coverage['column']}'"],
            drift_mode="time",
        )
    elif rows:
        other = _reference_candidates(db, owner_id, meta)
        modules["drift"] = _module(
            "partial",
            [
                "A drift score needs a reference distribution: an earlier period or a second dataset.",
                "This dataset has no usable date column, so a time-based comparison cannot be built.",
                "Drift numbers are not estimated or simulated in this state.",
            ],
            [
                "Upload a second dataset (for example the same source from another period)",
                "or include a date column to compare earlier and later periods",
            ],
            drift_mode="none",
            reference_candidates=other,
        )
    else:
        modules["drift"] = _module("unavailable", ["No data rows"], ["Upload a dataset"])

    if time_series_ready:
        modules["forecast"] = _module(
            "ready",
            [
                f"time-series forecast of a numeric measure over {time_coverage['periods']} {time_coverage['frequency']} periods",
            ],
            forecast_mode="time_series",
        )
    elif supervised_ready:
        modules["forecast"] = _module(
            "ready",
            [
                f"supervised prediction of confirmed target '{target['column']}'",
                "no date column, so this is a scoring model rather than a time-series forecast",
            ],
            forecast_mode="prediction",
        )
    elif target_ready and target and not target["confirmed"]:
        modules["forecast"] = _module(
            "partial",
            [
                f"'{target['column']}' looks like an outcome, but it is only a suggestion until you confirm it.",
                "No date column was found, so a time-series forecast cannot be produced.",
            ],
            ["Confirm (or choose) a prediction target in the Analysis Report"],
            forecast_mode="prediction",
        )
    else:
        modules["forecast"] = _module(
            "unavailable",
            ["needs either a date column with a numeric measure, or an outcome column for prediction"],
            ["A date column plus a numeric measure, or a confirmed target column"],
        )

    if target_ready or (rows >= MIN_ROWS and measures):
        modules["strategy"] = _module(
            "ready",
            [
                "prioritises the measured drivers behind the observed outcome"
                if target_ready else "summarises measured relationships between the available measures",
                "opportunities are labelled association-based, not proven savings",
            ],
        )
    else:
        modules["strategy"] = _module(
            "unavailable",
            ["needs an outcome column or several numeric measures"],
            ["An outcome column or numeric measures"],
        )

    modules["analysis"] = _module(
        "ready" if rows else "unavailable",
        ["profiling, exploratory statistics and the supported modelling task"],
        [] if rows else ["Upload a dataset"],
    )

    understanding = describe_understanding(roles, target, rows, time_coverage, schema)
    if understanding["domain"].startswith("Customer churn") and identifiers:
        subject_label = "customers"
    if target and target.get("kind") == "binary" and target.get("event") is not None:
        target["polarity"] = (
            f"'{target['event']}' is treated as the event class because the column is a churn-style flag. "
            "Verify this matches your source definition before acting on the rates."
        )

    capabilities = {
        "mode": "sales" if schema_id == "sales" else "adaptive",
        "schema": schema_id,
        "schema_label": schema.label,
        "dataset": {
            "id": meta.id,
            "name": meta.dataset_name,
            "rows": rows,
            "columns": int(len(frame.columns)),
            "uploaded_at": str(meta.uploaded_at) if meta.uploaded_at else None,
            "task": meta.analysis_task,
            "target": meta.target_field,
        },
        "roles": roles["roles"],
        "columns": roles["columns"],
        "measures": [{"column": column, "label": humanize(column)} for column in measures[:12]],
        "dimensions": [{"column": column, "label": humanize(column)} for column in dimensions[:12]],
        "subjects": {"column": identifiers[0] if identifiers else None, "count": subject_count, "label": subject_label},
        "has_time": bool(time_coverage),
        "time_coverage": time_coverage,
        "target": target,
        "target_suggestions": suggestions,
        "supervised_ready": supervised_ready,
        "understanding": understanding,
        "modules": modules,
    }
    cache.put_frame(cache_key, capabilities, frame)
    return capabilities, frame


def describe_understanding(
    roles: dict,
    target: Optional[dict],
    rows: int,
    time_coverage: Optional[dict],
    schema,
) -> dict:
    """Explain the structure the platform inferred, independently of the template."""
    evidence: list[str] = []
    churn_like = bool(target and any(
        word in str(target["column"]).lower()
        for word in ("churn", "attrition", "exit", "cancel", "retention", "defect")
    ))
    if churn_like and target:
        structure = "customer-level records with an observed churn outcome"
        domain = "Customer churn & retention"
        evidence.append(f"outcome column '{target['column']}' with {len(target.get('classes', []))} observed classes")
    elif target:
        structure = f"records with an observed outcome ('{target['column']}')"
        domain = "Outcome analysis"
        evidence.append(f"outcome column '{target['column']}'")
    elif time_coverage and roles["roles"]["measures"]:
        structure = "dated observations of numeric measures"
        domain = "Time series"
        evidence.append(f"'{time_coverage['column']}' covers {time_coverage.get('from')} → {time_coverage.get('to')}")
    else:
        structure = "tabular records"
        domain = "General exploratory"

    if roles["roles"]["identifiers"]:
        evidence.append(f"identifier column '{roles['roles']['identifiers'][0]}'")
    evidence.append(f"{len(roles['roles']['measures'])} numeric measures and {len(roles['roles']['binary']) + len(roles['roles']['categorical'])} grouping columns")
    if not time_coverage:
        evidence.append("no parseable date column, so there is no timeline")
    evidence.append(f"{rows:,} committed rows")

    template_note = (
        f"Stored template: {schema.label}. This dataset did not match a domain template strongly, "
        "so every analysis is selected from the columns and values above rather than the label."
        if schema.id in {"generic", "custom"}
        else f"Stored template: {schema.label}."
    )

    return {
        "structure": structure,
        "domain": domain,
        "evidence": evidence,
        "template_note": template_note,
    }


def _reference_candidates(db: Session, owner_id: str, active: DatasetMeta) -> list[dict]:
    rows = (
        db.query(DatasetMeta)
        .filter(DatasetMeta.owner_id == owner_id, DatasetMeta.id != active.id)
        .order_by(DatasetMeta.id.desc())
        .limit(8)
        .all()
    )
    return [
        {
            "id": row.id,
            "name": row.dataset_name,
            "schema": row.schema_kind,
            "rows": row.row_count or 0,
            "uploaded_at": str(row.uploaded_at) if row.uploaded_at else None,
        }
        for row in rows
    ]


def public_capabilities(capabilities: dict) -> dict:
    """Capabilities without oversized internals, ready for the API."""
    return capabilities
