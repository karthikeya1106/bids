"""
Explainable column mapping.

Every suggestion is scored from three independent signals — name similarity,
data-type compatibility and the column's value profile — and returned with the
reasons that produced it. Nothing is auto-mapped below the review threshold,
identifiers never become measures, and a source column is assigned to at most
one target field.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from services.profiling import coerce_datetime, coerce_numeric, json_safe
from services.schemas import (
    BOOLEAN,
    CATEGORICAL,
    DATETIME,
    IDENTIFIER,
    NUMERIC,
    TEXT,
    DatasetSchema,
    FieldSpec,
)
from services.semantics import (
    looks_like_date,
    looks_like_id,
    looks_like_measure,
    name_similarity,
)

AUTO_THRESHOLD = 0.62       # high enough to stand on its own
REVIEW_THRESHOLD = 0.46     # suggested but flagged for user review
GENERATE = "__generate__"
DERIVED = "__derived__"
UNMAPPED = ""


def _column_profile(profile: dict, name: str) -> Optional[dict]:
    for column in profile["column_profiles"]:
        if column["name"] == name:
            return column
    return None


def _type_fit(spec: FieldSpec, column: dict) -> tuple[float, list[str]]:
    """Compatibility between a target field and a source column's inferred type."""
    dtype = column["dtype"]
    reasons: list[str] = []

    if spec.dtype == DATETIME:
        if dtype == DATETIME:
            reasons.append("values parse as dates")
            return 1.0, reasons
        if column.get("date_parse_pct", 0) >= 85:
            reasons.append("values parse as dates")
            return 0.6, reasons
        return 0.0, ["values are not dates"]

    if spec.dtype == NUMERIC:
        if dtype == NUMERIC:
            reasons.append("numeric values")
            return 1.0, reasons
        if dtype == BOOLEAN:
            reasons.append("binary values can act as a number")
            return 0.55, reasons
        if column.get("numeric_parse_pct", 0) >= 90:
            reasons.append("numeric values")
            return 0.7, reasons
        return 0.0, ["values are not numeric"]

    if spec.dtype == IDENTIFIER:
        if dtype == IDENTIFIER:
            reasons.append("distinct identifier values")
            return 1.0, reasons
        if dtype in (NUMERIC, TEXT) and column["unique_ratio"] >= 0.9:
            reasons.append("(almost) unique values")
            return 0.75, reasons
        # A customer or product key legitimately repeats once per transaction;
        # rejecting repeats would leave customer-level analytics without a key.
        if column["unique"] >= 5 and column["unique_ratio"] >= 0.02:
            reasons.append(f"{column['unique']} distinct values that repeat per row, as a key does")
            return 0.8, reasons
        if column["unique"] <= 2:
            return 0.15, ["only one or two distinct values — not an identifier"]
        return 0.35, ["too few distinct values for an identifier"]

    if spec.dtype == CATEGORICAL:
        if dtype in (CATEGORICAL, BOOLEAN):
            reasons.append("low-cardinality categories")
            return 1.0, reasons
        if dtype == NUMERIC and column["unique"] <= 20:
            reasons.append("small integer-coded categories")
            return 0.7, reasons
        if dtype == TEXT:
            return 0.5, reasons
        if column["unique_ratio"] >= 0.9:
            return 0.1, ["nearly every row is unique; not a category"]
        return 0.4, reasons

    # TEXT accepts anything readable.
    if dtype in (TEXT, CATEGORICAL):
        return 1.0, reasons
    return 0.6, reasons


def _value_fit(spec: FieldSpec, column: dict) -> tuple[float, list[str]]:
    """Distribution-level evidence for or against the target field."""
    reasons: list[str] = []
    if column["missing_pct"] >= 60 and spec.required:
        return 0.2, ["mostly empty in this file"]

    if spec.dtype == IDENTIFIER:
        if column["unique_ratio"] >= 0.95:
            reasons.append(f"{column['unique_ratio'] * 100:.0f}% distinct values")
            return 1.0, reasons
        if column["unique"] <= 2:
            return 0.1, ["one or two distinct values cannot identify a record"]
        reasons.append(f"{column['unique']} distinct values, repeated across rows")
        return 0.75, reasons

    if spec.dtype == NUMERIC:
        if column["unique"] <= 1:
            return 0.1, ["constant column"]
        if spec.key in {"discount"} and column.get("max", 0) <= 1:
            reasons.append("stored as a 0–1 ratio")
            return 1.0, reasons
        return 1.0, reasons

    if spec.dtype == CATEGORICAL:
        if 2 <= column["unique"] <= 50:
            reasons.append(f"{column['unique']} categories")
            return 1.0, reasons
        if column["unique"] == 1:
            return 0.1, ["single category"]

    if spec.dtype == DATETIME and column.get("date_min"):
        reasons.append(f"covers {column['date_min']} → {column['date_max']}")
        return 1.0, reasons

    return 0.7, reasons


def _semantic_penalty(spec: FieldSpec, source_name: str) -> tuple[float, list[str]]:
    """Guard against type-compatible but semantically wrong assignments."""
    factor, reasons = 1.0, []
    source_is_id = looks_like_id(source_name)
    source_is_measure = looks_like_measure(source_name)

    if spec.dtype == IDENTIFIER and source_is_measure and not source_is_id:
        factor *= 0.25
        reasons.append("column reads as a measurement, not an identifier")
    if spec.dtype in (NUMERIC, DATETIME) and source_is_id and not looks_like_date(source_name):
        factor *= 0.3
        reasons.append("column reads as an identifier, not a measurement")
    if spec.dtype == TEXT and source_is_id:
        # "Customer ID" holds keys, not human-readable names.
        factor *= 0.55
        reasons.append("column reads as an identifier, not free text")
    if spec.dtype == DATETIME and not looks_like_date(source_name):
        factor *= 0.85
    return factor, reasons


def score_field(
    spec: FieldSpec,
    column_name: str,
    column: dict,
    df: pd.DataFrame,
) -> dict:
    """Score one (target field, source column) pair with a human explanation."""
    name_score = 0.0
    matched_alias = ""
    for alias in (spec.key, *spec.aliases):
        similarity = name_similarity(column_name, alias)
        if similarity > name_score:
            name_score, matched_alias = similarity, alias

    type_score, type_reasons = _type_fit(spec, column)
    value_score, value_reasons = _value_fit(spec, column)
    penalty, penalty_reasons = _semantic_penalty(spec, column_name)

    score = (0.75 * name_score + 0.15 * type_score + 0.10 * value_score) * penalty
    # Type and value compatibility alone are never enough: a column must also
    # resemble the target field by name, otherwise unrelated measurements get
    # mapped to business fields just because they are numeric.
    if name_score < 0.5:
        score *= 0.2
    score = round(min(1.0, max(0.0, score)), 3)

    reasons: list[str] = []
    if name_score >= 0.95:
        reasons.append(f"column name matches '{matched_alias}'")
    elif name_score >= 0.7:
        reasons.append(f"column name closely resembles '{matched_alias}'")
    elif name_score >= 0.45:
        reasons.append(f"column name partly resembles '{matched_alias}'")
    else:
        reasons.append("column name does not resemble this field")
    reasons.extend(type_reasons)
    reasons.extend(value_reasons)
    reasons.extend(penalty_reasons)

    return {
        "score": score,
        "name_score": round(name_score, 3),
        "type_score": round(type_score, 3),
        "value_score": round(value_score, 3),
        "compatible": type_score > 0,
        "reasons": reasons,
    }


def confidence_label(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= AUTO_THRESHOLD:
        return "medium"
    if score >= REVIEW_THRESHOLD:
        return "low"
    return "none"


def suggest_mapping(
    df: pd.DataFrame,
    profile: dict,
    schema: DatasetSchema,
) -> dict[str, dict]:
    """One-to-one explainable suggestions for every declarative field."""
    columns = [column["name"] for column in profile["column_profiles"]]
    profiles = {column["name"]: column for column in profile["column_profiles"]}
    fields = schema.mapped_fields()

    candidates: list[dict] = []
    for spec in fields:
        for column_name in columns:
            column = profiles[column_name]
            scored = score_field(spec, column_name, column, df)
            if scored["score"] < REVIEW_THRESHOLD or not scored["compatible"]:
                continue
            candidates.append({"field": spec, "column": column_name, **scored})

    candidates.sort(key=lambda item: item["score"], reverse=True)

    assigned: dict[str, dict] = {}
    used_columns: dict[str, str] = {}
    alternatives: dict[str, list[dict]] = {}
    for candidate in candidates:
        field_key = candidate["field"].key
        column_name = candidate["column"]
        alternatives.setdefault(field_key, [])
        if len(alternatives[field_key]) < 3:
            alternatives[field_key].append({
                "column": column_name,
                "score": candidate["score"],
            })
        if field_key in assigned or column_name in used_columns:
            continue
        if candidate["score"] < REVIEW_THRESHOLD:
            continue
        assigned[field_key] = candidate
        used_columns[column_name] = field_key

    decisions: dict[str, dict] = {}
    for spec in spec_all_fields(schema):
        if spec.derive:
            source_keys = derivation_sources(spec.derive, schema)
            present = [key for key in source_keys if key in {c["field"].key for c in assigned.values()}]
            if len(present) == len(source_keys) and source_keys:
                decisions[spec.key] = _decision(
                    spec, DERIVED, None, 0.99, "derived",
                    [f"computed from {', '.join(present)}"],
                    derived_from=present,
                )
            else:
                decisions[spec.key] = _decision(
                    spec, UNMAPPED, None, 0.0, "unavailable",
                    [f"needs {', '.join(source_keys) or 'source columns'}"],
                )
            continue

        candidate = assigned.get(spec.key)
        if candidate:
            column = profiles[candidate["column"]]
            status = "auto" if candidate["score"] >= AUTO_THRESHOLD else "needs_review"
            decisions[spec.key] = _decision(
                spec,
                candidate["column"],
                column,
                candidate["score"],
                status,
                candidate["reasons"],
                alternatives=alternatives.get(spec.key, []),
            )
        elif spec.allow_generated:
            decisions[spec.key] = _decision(
                spec, GENERATE, None, 0.0, "generated",
                ["no source column found — a labelled technical row index will be created"],
            )
        elif spec.required:
            best = (alternatives.get(spec.key) or [{}])[0]
            decisions[spec.key] = _decision(
                spec, UNMAPPED, None, best.get("score", 0.0), "unmapped",
                [f"no compatible column found (best candidate: {best.get('column', 'none')})"],
                alternatives=alternatives.get(spec.key, []),
            )
        else:
            decisions[spec.key] = _decision(
                spec, UNMAPPED, None, 0.0, "unmapped",
                ["optional field left unmapped"],
                alternatives=alternatives.get(spec.key, []),
            )

    return decisions


def spec_all_fields(schema: DatasetSchema) -> list[FieldSpec]:
    return list(schema.fields)


def _decision(
    spec: FieldSpec,
    column: Any,
    column_profile: Optional[dict],
    score: float,
    status: str,
    reasons: list[str],
    alternatives: Optional[list[dict]] = None,
    derived_from: Optional[list[str]] = None,
) -> dict:
    return {
        "field": spec.key,
        "label": spec.label,
        "description": spec.description,
        "dtype": spec.dtype,
        "required": spec.required,
        "target": spec.target,
        "role": spec.role,
        "allow_generated": spec.allow_generated,
        "value": column,
        "column": column if column not in (GENERATE, DERIVED, UNMAPPED, None) else None,
        "score": round(float(score), 3),
        "confidence": confidence_label(score) if status not in ("derived", "generated") else status,
        "status": status,
        "reasons": reasons,
        "alternatives": alternatives or [],
        "derived_from": derived_from or [],
        "sample_values": (column_profile or {}).get("sample_values", []),
        "source_dtype": (column_profile or {}).get("dtype"),
    }


def derivation_sources(rule: str, schema: DatasetSchema) -> list[str]:
    """Source fields required by a derivation rule."""
    rules = {
        "sum_charges": ["day_charge", "eve_charge", "night_charge", "intl_charge"],
        "profit_margin": ["profit", "sales"] if schema.id == "sales" else ["profit", "revenue"],
        "click_through_rate": ["clicks", "impressions"],
        "return_on_ad_spend": ["revenue", "spend"],
    }
    return rules.get(rule, [])


def apply_derivation(rule: str, record: dict) -> Optional[float]:
    """Compute a derived numeric field from canonical record values.

    Returns None when any required input is missing, so nothing is invented.
    """
    def num(key: str) -> Optional[float]:
        value = record.get(key)
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    if rule == "sum_charges":
        parts = [num(key) for key in ("day_charge", "eve_charge", "night_charge", "intl_charge")]
        if any(part is None for part in parts):
            return None
        return round(float(sum(parts)), 2)

    if rule == "profit_margin":
        profit = num("profit")
        revenue = num("sales") if num("sales") is not None else num("revenue")
        if profit is None or revenue in (None, 0):
            return None
        return round(profit / revenue * 100, 2)

    if rule == "click_through_rate":
        clicks, impressions = num("clicks"), num("impressions")
        if clicks is None or impressions in (None, 0):
            return None
        return round(clicks / impressions * 100, 3)

    if rule == "return_on_ad_spend":
        revenue, spend = num("revenue"), num("spend")
        if revenue is None or spend in (None, 0):
            return None
        return round(revenue / spend, 3)

    return None


def coerce_value(value: Any, dtype: str) -> Any:
    """Convert one raw cell to a canonical value for storage."""
    if value is None:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    if isinstance(value, str) and not value.strip():
        return None

    if dtype == NUMERIC:
        parsed = coerce_numeric(pd.Series([value])).iloc[0]
        if pd.isna(parsed):
            return None
        as_float = float(parsed)
        return int(as_float) if as_float.is_integer() else round(as_float, 6)

    if dtype == DATETIME:
        parsed = coerce_datetime(pd.Series([value])).iloc[0]
        if pd.isna(parsed):
            return None
        return pd.Timestamp(parsed).date().isoformat()

    if dtype == BOOLEAN:
        text = str(value).strip().lower()
        if text in {"true", "yes", "y", "1", "t"}:
            return "Yes"
        if text in {"false", "no", "n", "0", "f"}:
            return "No"
        return str(value).strip()

    return str(value).strip()[:500]
