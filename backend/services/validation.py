"""
Data validation.

Runs after mapping and before ingestion. Every check reports a concrete status
and detail so the UI never shows "ready" for a file that cannot actually be
analysed, and the commit endpoint re-runs the same checks server-side.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from services import schemas as schema_module
from services.mapping import DERIVED, GENERATE, derivation_sources
from services.profiling import coerce_datetime, coerce_numeric, detect_frequency
from services.schemas import (
    CATEGORICAL,
    DATETIME,
    IDENTIFIER,
    NUMERIC,
    TEXT,
    DatasetSchema,
)

MAX_ROWS = 200_000
MIN_MODEL_ROWS = 30
PRIMARY_IDENTIFIERS = {
    "order_id", "subscriber_id", "transaction_id", "employee_id", "campaign_id",
}


def _check(
    checks: list[dict],
    check_id: str,
    label: str,
    status: str,
    detail: str,
    field: Optional[str] = None,
    rows: Optional[int] = None,
) -> None:
    checks.append({
        "id": check_id,
        "label": label,
        "status": status,  # pass | warn | fail | info
        "detail": detail,
        "field": field,
        "rows": rows,
    })


def _parse_rate(column: pd.Series, dtype: str) -> tuple[float, int, int]:
    non_null = column.notna().sum()
    if non_null == 0:
        return 0.0, 0, 0
    if dtype == NUMERIC:
        parsed = coerce_numeric(column)
    elif dtype == DATETIME:
        parsed = coerce_datetime(column)
    else:
        return 1.0, 0, int(non_null)
    valid = int(parsed.notna().sum())
    return valid / int(non_null), valid, int(non_null)


def _class_counts(series: pd.Series) -> dict[str, int]:
    cleaned = series.dropna().astype(str).str.strip().str.lower()
    return {str(key): int(value) for key, value in cleaned.value_counts().items()}


def forecast_readiness(
    df: pd.DataFrame,
    time_column: Optional[str],
    target_column: Optional[str],
    frequency_hint: Optional[str] = None,
) -> dict:
    """Whether a real time series exists, and why not when it doesn't."""
    reasons: list[str] = []
    if not time_column or time_column not in df.columns:
        return {"available": False, "reasons": ["no date column mapped to a time field"]}
    if not target_column or target_column not in df.columns:
        return {"available": False, "reasons": ["no numeric measure selected to forecast"]}

    dates = coerce_datetime(df[time_column])
    values = coerce_numeric(df[target_column])
    valid = dates.notna() & values.notna()
    if int(valid.sum()) < 12:
        reasons.append(f"only {int(valid.sum())} complete date/value rows (need at least 12)")
    if dates.notna().sum() == 0:
        reasons.append(f"'{time_column}' contains no parseable dates")

    coverage = detect_frequency(dates.dropna())
    if coverage:
        if coverage["periods"] < 3:
            reasons.append(f"only {coverage['periods']} distinct periods of history")
        if coverage["coverage"] < 0.5:
            reasons.append(f"timeline coverage is {coverage['coverage'] * 100:.0f}% — large gaps")
    else:
        reasons.append("could not infer a reporting period")

    return {
        "available": not reasons,
        "reasons": reasons,
        "time_column": time_column,
        "target": target_column,
        "frequency": coverage.get("frequency") if coverage else frequency_hint,
        "periods": coverage.get("periods") if coverage else 0,
        "coverage": coverage.get("coverage") if coverage else 0,
        "from": coverage.get("from") if coverage else None,
        "to": coverage.get("to") if coverage else None,
    }


def validate_dataset(
    df: pd.DataFrame,
    profile: dict,
    schema: DatasetSchema,
    mapping: dict[str, str],
    task: str = "eda",
    target: Optional[str] = None,
) -> dict:
    """Validate mappings, types, completeness and model readiness."""
    checks: list[dict] = []
    capabilities: dict[str, bool] = {}
    fields = schema.field_map() if schema.fields else {}

    if df.empty:
        _check(checks, "rows", "Data rows", "fail", "The file has no data rows.")
    elif len(df) > MAX_ROWS:
        _check(
            checks, "rows", "Data rows", "fail",
            f"{len(df):,} rows exceeds the {MAX_ROWS:,}-row limit. Split the file.",
        )
    else:
        _check(checks, "rows", "Data rows", "pass", f"{len(df):,} rows available.")

    if not df.columns.size:
        _check(checks, "columns", "Columns", "fail", "The file has no columns.")

    # ── Per-field mapping and type checks ────────────────────────────────────
    mapped_columns: dict[str, str] = {}
    for key, spec in fields.items():
        value = mapping.get(key) or ""
        if spec.derive:
            required_sources = derivation_sources(spec.derive, schema)
            present = [source for source in required_sources if mapping.get(source)]
            if required_sources and len(present) == len(required_sources):
                _check(
                    checks, f"derived:{key}", spec.label, "pass",
                    f"derived from {', '.join(present)}", field=key,
                )
            else:
                _check(
                    checks, f"derived:{key}", spec.label, "info",
                    f"not derived — needs {', '.join(required_sources) or 'source fields'}",
                    field=key,
                )
            continue

        if value == GENERATE:
            if spec.allow_generated:
                _check(
                    checks, f"generated:{key}", spec.label, "info",
                    "no source identifier — a labelled technical row index will be generated",
                    field=key,
                )
            else:
                _check(
                    checks, f"missing:{key}", spec.label, "fail",
                    "a source column is required but none is mapped", field=key,
                )
            continue

        if not value or value == DERIVED:
            if spec.required:
                _check(
                    checks, f"missing:{key}", spec.label, "fail",
                    "required field is not mapped", field=key,
                )
            else:
                _check(
                    checks, f"optional:{key}", spec.label, "info",
                    "optional field not mapped", field=key,
                )
            continue

        if value not in df.columns:
            _check(
                checks, f"unknown:{key}", spec.label, "fail",
                f"'{value}' is not a column in this file", field=key,
            )
            continue

        mapped_columns[key] = value
        column = df[value]
        missing_pct = float(column.isna().mean() * 100)

        rate, valid, non_null = _parse_rate(column, spec.dtype)
        if spec.dtype in (NUMERIC, DATETIME):
            if rate >= 0.95:
                _check(
                    checks, f"type:{key}", f"{spec.label} type", "pass",
                    f"{valid:,} of {non_null:,} values are valid {spec.dtype}s", field=key,
                )
            elif rate >= 0.8:
                _check(
                    checks, f"type:{key}", f"{spec.label} type", "warn",
                    f"{non_null - valid:,} of {non_null:,} values cannot be parsed as {spec.dtype}s; "
                    "they will be left empty", field=key, rows=non_null - valid,
                )
            else:
                _check(
                    checks, f"type:{key}", f"{spec.label} type",
                    "fail" if spec.required else "warn",
                    f"only {rate * 100:.0f}% of values parse as {spec.dtype}s", field=key,
                )

        # Only primary identifiers must be unique. A customer id on an order
        # line legitimately repeats for every purchase.
        if spec.dtype == IDENTIFIER and spec.key in PRIMARY_IDENTIFIERS:
            unique_ratio = float(column.dropna().nunique() / max(1, column.notna().sum()))
            if unique_ratio >= 0.95:
                _check(
                    checks, f"id:{key}", f"{spec.label} uniqueness", "pass",
                    f"{unique_ratio * 100:.1f}% distinct values", field=key,
                )
            else:
                _check(
                    checks, f"id:{key}", f"{spec.label} uniqueness", "warn",
                    f"only {unique_ratio * 100:.1f}% distinct values — identifiers repeat", field=key,
                )

        if missing_pct >= 30:
            _check(
                checks, f"missing_pct:{key}", f"{spec.label} completeness",
                "fail" if spec.required else "warn",
                f"{missing_pct:.1f}% of values are empty", field=key,
            )
        elif missing_pct > 0:
            _check(
                checks, f"missing_pct:{key}", f"{spec.label} completeness", "warn",
                f"{missing_pct:.1f}% of values are empty", field=key,
            )

    # ── Dataset-level findings ────────────────────────────────────────────────
    if len(df):
        duplicate_rows = int(df.duplicated().sum())
        if duplicate_rows:
            _check(
                checks, "duplicate_rows", "Duplicate rows",
                "warn" if duplicate_rows / len(df) >= 0.05 else "info",
                f"{duplicate_rows:,} fully duplicated rows", rows=duplicate_rows,
            )

    # Required fields specific to the chosen task.
    target_column = None
    if target:
        target_spec = fields.get(target)
        if target_spec is None and schema.custom:
            target_column = target if target in df.columns else None
        elif target_spec and target_spec.key in mapped_columns:
            target_column = mapped_columns[target_spec.key]
        elif target in mapped_columns:
            target_column = mapped_columns[target]
        elif target in df.columns:
            target_column = target
        else:
            _check(
                checks, "target", "Analysis target", "fail",
                f"target '{target}' is not mapped to a source column", field=target,
            )

    forecast: Optional[dict] = None
    if task == "classification":
        if not target_column:
            _check(checks, "task:classification", "Classification readiness", "fail",
                   "choose a target column with two or more classes")
        else:
            classes = _class_counts(df[target_column])
            smallest = min(classes.values()) if classes else 0
            if len(classes) < 2:
                _check(checks, "task:classification", "Classification readiness", "fail",
                       "the target has only one class", field=target_column)
            elif len(classes) > 30:
                _check(checks, "task:classification", "Classification readiness", "fail",
                       f"the target has {len(classes)} classes; classification needs a limited label set",
                       field=target_column)
            elif len(df) < MIN_MODEL_ROWS:
                _check(checks, "task:classification", "Classification readiness", "fail",
                       f"{len(df)} rows is below the {MIN_MODEL_ROWS}-row minimum", field=target_column)
            else:
                status = "pass" if smallest >= 5 else "warn"
                _check(
                    checks, "task:classification", "Classification readiness", status,
                    f"{len(classes)} classes, smallest has {smallest} rows", field=target_column,
                )

    if task == "regression":
        if not target_column:
            _check(checks, "task:regression", "Regression readiness", "fail",
                   "choose a continuous numeric target")
        else:
            values = coerce_numeric(df[target_column])
            if values.notna().sum() < MIN_MODEL_ROWS:
                _check(checks, "task:regression", "Regression readiness", "fail",
                       f"only {int(values.notna().sum())} numeric values", field=target_column)
            elif values.std() == 0:
                _check(checks, "task:regression", "Regression readiness", "fail",
                       "the target is constant", field=target_column)
            else:
                _check(checks, "task:regression", "Regression readiness", "pass",
                       f"target has variance {values.var():.2f}", field=target_column)

    if task == "clustering":
        numeric_mapped = [
            spec.key for spec in fields.values()
            if spec.dtype == NUMERIC and spec.key in mapped_columns
        ]
        if len(numeric_mapped) >= 2:
            _check(checks, "task:clustering", "Clustering readiness", "pass",
                   f"{len(numeric_mapped)} numeric features available")
        else:
            _check(checks, "task:clustering", "Clustering readiness", "fail",
                   "clustering needs at least 2 mapped numeric fields")

    if task == "forecast":
        time_column = next(
            (mapped_columns[spec.key] for spec in fields.values()
             if spec.dtype == DATETIME and spec.role == "time" and spec.key in mapped_columns),
            next((mapped_columns[spec.key] for spec in fields.values()
                  if spec.dtype == DATETIME and spec.key in mapped_columns), None),
        )
        forecast = forecast_readiness(df, time_column, target_column)
        _check(
            checks, "task:forecast", "Forecast readiness",
            "pass" if forecast["available"] else "fail",
            (
                f"{forecast['frequency']} series with {forecast['periods']} periods"
                if forecast["available"]
                else "; ".join(forecast["reasons"])
            ),
            field=target_column,
        )

    # ── Capabilities used by the modules ─────────────────────────────────────
    capabilities = {
        "has_customer": any(key in mapped_columns for key in ("customer_id", "subscriber_id")),
        "has_profit": "profit" in mapped_columns or any(
            checked["field"] == "profit_margin" and checked["status"] == "pass" for checked in checks
        ),
        "has_discount": "discount" in mapped_columns,
        "has_product": any(key in mapped_columns for key in ("product_name", "product_id")),
        "has_region": any(key in mapped_columns for key in ("region", "state", "warehouse")),
        "has_time": any(
            fields[key].dtype == DATETIME for key in mapped_columns if key in fields
        ),
        "has_target": bool(target_column),
    }

    errors = sum(1 for check in checks if check["status"] == "fail")
    warnings = sum(1 for check in checks if check["status"] == "warn")
    required_missing = [
        spec.key for spec in schema.required_fields()
        if not mapping.get(spec.key) and not spec.derive
    ]
    if schema.id == "generic" and not df.columns.size:
        required_missing.append("columns")

    return {
        "ready": errors == 0,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "target": target_column,
        "task": task,
        "forecast": forecast,
        "capabilities": capabilities,
        "required_missing": required_missing,
        "mapped_fields": len(mapped_columns),
        "total_fields": len([spec for spec in schema.fields if not spec.derive]),
    }


def modules_supported(schema_id: str, capabilities: dict, forecast: Optional[dict]) -> dict:
    """Which analytics modules can genuinely run on this dataset."""
    sales = schema_id == "sales"
    churn = schema_id == "churn"
    customer_level = capabilities.get("has_customer", False)
    return {
        "dashboard": sales,
        "behavior": (sales and customer_level) or churn,
        "segmentation": (sales and customer_level) or churn,
        "rootcause": sales and capabilities.get("has_time", False),
        "drift": sales and capabilities.get("has_time", False),
        "forecast": sales and capabilities.get("has_time", False),
        "strategy": sales,
        "analysis": True,
        "adaptive_report": not sales,
    }
