"""
Dataset profiling.

Builds a JSON-serialisable profile of an uploaded table: per-column semantic
types, completeness, cardinality, distributions, outliers, time coverage,
correlations and data-quality findings. Only small samples are returned so
customer-level records are never echoed back in full.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

import numpy as np
import pandas as pd

from services.schemas import (
    BOOLEAN,
    CATEGORICAL,
    DATETIME,
    IDENTIFIER,
    NUMERIC,
    TEXT,
)
from services.semantics import humanize, looks_like_date, looks_like_id, tokens

SAMPLE_VALUES = 5
TOP_VALUES = 8
MAX_CORRELATION_ROWS = 5000
_BOOLEANS = {"true", "false", "yes", "no", "y", "n", "1", "0", "t", "f"}
_DATE_SAMPLE = 200


def json_safe(value: Any) -> Any:
    """Convert numpy/pandas scalars into JSON-friendly Python values."""
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else round(float(value), 4)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.date().isoformat() if hasattr(value, "date") else str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and np.isnan(value):
        return None
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def coerce_numeric(series: pd.Series) -> pd.Series:
    """Parse numbers with currency separators; unparseable values become NaN."""
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    cleaned = (
        series.astype(str)
        .str.replace(r"[,\s]", "", regex=True)
        .str.replace(r"^[\$€£₹]", "", regex=True)
        .str.replace(r"%$", "", regex=True)
        .replace({"": np.nan, "nan": np.nan, "None": np.nan, "NULL": np.nan})
    )
    return pd.to_numeric(cleaned, errors="coerce")


def coerce_datetime(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", format="mixed")


def _sample(series: pd.Series) -> list[Any]:
    values: list[Any] = []
    for value in series.dropna().unique()[:SAMPLE_VALUES]:
        values.append(json_safe(value))
    return values


def infer_column_type(series: pd.Series, name: str) -> tuple[str, pd.Series]:
    """Return (semantic type, parsed series) for one column."""
    non_null = series.dropna()
    if non_null.empty:
        return TEXT, series

    if pd.api.types.is_bool_dtype(series):
        return BOOLEAN, series
    if pd.api.types.is_datetime64_any_dtype(series):
        return DATETIME, pd.to_datetime(series, errors="coerce")

    unique_count = int(non_null.nunique())
    unique_ratio = unique_count / len(non_null) if len(non_null) else 0.0
    if looks_like_id(name) and unique_ratio >= 0.9 and unique_count > 1:
        return IDENTIFIER, series

    if pd.api.types.is_numeric_dtype(series):
        return NUMERIC, pd.to_numeric(series, errors="coerce")

    text_sample = non_null.astype(str).head(500)
    lowered = set(text_sample.str.strip().str.lower().unique())
    if len(lowered) <= 2 and lowered and lowered.issubset(_BOOLEANS):
        return BOOLEAN, series

    numeric_sample = coerce_numeric(text_sample)
    numeric_rate = float(numeric_sample.notna().mean()) if len(text_sample) else 0.0
    if numeric_rate >= 0.95:
        return NUMERIC, coerce_numeric(series)

    date_sample = non_null.astype(str).head(_DATE_SAMPLE)
    parsed_dates = coerce_datetime(date_sample)
    date_rate = float(parsed_dates.notna().mean()) if len(date_sample) else 0.0
    # Only treat as dates when most values parse and the name or the values
    # contain a date separator; random integers must not become timestamps.
    separator_hint = bool(
        date_sample.astype(str).str.contains(r"[-/:T]", regex=True).mean() >= 0.8
    )
    if date_rate >= 0.85 and (separator_hint or looks_like_date(name)):
        return DATETIME, coerce_datetime(series)

    if unique_count <= 50 or unique_ratio <= 0.05:
        return CATEGORICAL, series
    return TEXT, series


def _numeric_stats(series: pd.Series) -> dict:
    parsed = coerce_numeric(series).dropna()
    if parsed.empty:
        return {}
    q1, q3 = parsed.quantile(0.25), parsed.quantile(0.75)
    iqr = q3 - q1
    outliers = int(
        ((parsed < q1 - 1.5 * iqr) | (parsed > q3 + 1.5 * iqr)).sum()
    ) if iqr > 0 else 0
    return {
        "min": json_safe(parsed.min()),
        "max": json_safe(parsed.max()),
        "mean": json_safe(parsed.mean()),
        "median": json_safe(parsed.median()),
        "std": json_safe(parsed.std()),
        "zeros": int((parsed == 0).sum()),
        "outliers": outliers,
        "outlier_pct": round(outliers / len(parsed) * 100, 2),
    }


def _top_values(series: pd.Series) -> list[dict]:
    counts = series.dropna().astype(str).value_counts().head(TOP_VALUES)
    total = int(len(series.dropna()))
    return [
        {
            "value": str(value)[:120],
            "count": int(count),
            "share": round(int(count) / total * 100, 1) if total else 0.0,
        }
        for value, count in counts.items()
    ]


def profile_column(series: pd.Series, name: str) -> dict:
    dtype, parsed = infer_column_type(series, name)
    total = int(len(series))
    missing = int(series.isna().sum())
    non_null = total - missing
    unique = int(series.dropna().nunique())
    unique_ratio = round(unique / non_null, 4) if non_null else 0.0

    malformed = 0
    if dtype == NUMERIC:
        parsed_non_null = coerce_numeric(series)
        malformed = int(parsed_non_null.isna().sum() - missing)
    elif dtype == DATETIME:
        parsed_dates = coerce_datetime(series)
        malformed = int(parsed_dates.isna().sum() - missing)

    # Parse rates let the mapping engine reject a text column for a numeric or
    # date field even when the column name looks right. Sampled for speed.
    sample_values = series.dropna().astype(str).head(2000)
    numeric_parse_pct = 100.0 if dtype == NUMERIC else round(
        float(coerce_numeric(sample_values).notna().mean() * 100), 2
    ) if len(sample_values) else 0.0
    date_parse_pct = 100.0 if dtype == DATETIME else round(
        float(coerce_datetime(sample_values).notna().mean() * 100), 2
    ) if len(sample_values) else 0.0

    profile = {
        "name": name,
        "label": humanize(name),
        "dtype": dtype,
        "pandas_type": str(series.dtype),
        "missing": missing,
        "missing_pct": round(missing / total * 100, 2) if total else 0.0,
        "unique": unique,
        "unique_ratio": unique_ratio,
        "malformed": max(0, malformed),
        "numeric_parse_pct": numeric_parse_pct,
        "date_parse_pct": date_parse_pct,
        "sample_values": _sample(series),
        "top_values": _top_values(series) if dtype not in (NUMERIC, DATETIME, IDENTIFIER) else [],
        "flags": [],
    }

    if dtype == NUMERIC:
        profile.update(_numeric_stats(series))
        if unique <= 1:
            profile["flags"].append("constant")

    if dtype == DATETIME:
        parsed_dates = coerce_datetime(series).dropna()
        if not parsed_dates.empty:
            profile["date_min"] = json_safe(parsed_dates.min())
            profile["date_max"] = json_safe(parsed_dates.max())
        profile["flags"].append("time")

    if dtype == IDENTIFIER:
        profile["flags"].append("identifier")
        if unique_ratio < 0.95:
            profile["flags"].append("non_unique_identifier")

    if dtype == CATEGORICAL and unique > 50:
        profile["flags"].append("high_cardinality")
    if non_null and unique == 1:
        profile["flags"].append("constant")

    return profile


def detect_frequency(dates: pd.Series, max_periods: int = 4000) -> dict:
    """Infer the natural period of a date column and report coverage/gaps."""
    parsed = coerce_datetime(dates).dropna().sort_values()
    if parsed.empty:
        return {}
    unique = parsed.dt.normalize().drop_duplicates()
    if len(unique) > max_periods:
        unique = unique.iloc[:: max(1, len(unique) // max_periods)]

    span_days = max(1, int((parsed.max() - parsed.min()).days))
    observations = int(len(parsed))
    gaps = unique.diff().dt.days.dropna()
    median_gap = float(gaps.median()) if len(gaps) else span_days

    if median_gap <= 1:
        frequency, days = "daily", 1
    elif median_gap <= 3:
        frequency, days = "2-3 days", 2
    elif median_gap <= 10:
        frequency, days = "weekly", 7
    elif median_gap <= 20:
        frequency, days = "fortnightly", 14
    elif median_gap <= 45:
        frequency, days = "monthly", 30
    elif median_gap <= 120:
        frequency, days = "quarterly", 91
    else:
        frequency, days = "yearly", 365

    expected = max(1, int(span_days / days) + 1)
    observed = int(unique.nunique())
    coverage = round(min(1.0, observed / expected), 3)

    # Largest gap relative to the detected period.
    largest_gap = int(gaps.max()) if len(gaps) else 0
    missing_periods = max(0, expected - observed)

    return {
        "from": json_safe(parsed.min()),
        "to": json_safe(parsed.max()),
        "frequency": frequency,
        "median_gap_days": round(median_gap, 1),
        "observations": observations,
        "periods": observed,
        "expected_periods": expected,
        "missing_periods": missing_periods,
        "coverage": coverage,
        "largest_gap_days": largest_gap,
        "span_days": span_days,
    }


def _quality_findings(profiles: list[dict], df: pd.DataFrame, duplicate_rows: int) -> list[dict]:
    findings: list[dict] = []
    total_rows = len(df)

    if total_rows == 0:
        findings.append({
            "id": "empty_dataset", "level": "error", "column": None,
            "message": "The file contains a header but no data rows.",
        })
    elif total_rows < 30:
        findings.append({
            "id": "small_dataset", "level": "warning", "column": None,
            "message": f"Only {total_rows} rows. Statistical models need at least 30 rows.",
        })

    if duplicate_rows:
        share = duplicate_rows / total_rows * 100 if total_rows else 0
        findings.append({
            "id": "duplicate_rows",
            "level": "warning" if share >= 5 else "info",
            "column": None,
            "rows": duplicate_rows,
            "message": f"{duplicate_rows:,} fully duplicated rows ({share:.1f}% of the file).",
        })

    for profile in profiles:
        name = profile["name"]
        if profile["missing_pct"] >= 30:
            findings.append({
                "id": f"missing:{name}", "level": "warning", "column": name,
                "rows": profile["missing"],
                "message": f"{profile['missing_pct']:.1f}% of '{name}' is empty "
                           f"({profile['missing']:,} rows).",
            })
        elif profile["missing"]:
            findings.append({
                "id": f"missing:{name}", "level": "info", "column": name,
                "rows": profile["missing"],
                "message": f"{profile['missing']:,} empty values in '{name}' "
                           f"({profile['missing_pct']:.1f}%).",
            })
        if profile["malformed"]:
            findings.append({
                "id": f"malformed:{name}", "level": "warning", "column": name,
                "rows": profile["malformed"],
                "message": f"{profile['malformed']:,} values in '{name}' do not match the "
                           f"inferred {profile['dtype']} type.",
            })
        if "constant" in profile["flags"]:
            findings.append({
                "id": f"constant:{name}", "level": "info", "column": name,
                "message": f"'{name}' has a single distinct value and cannot explain variation.",
            })
        if "non_unique_identifier" in profile["flags"]:
            findings.append({
                "id": f"dup_id:{name}", "level": "warning", "column": name,
                "rows": int(total_rows - profile["unique"]),
                "message": f"'{name}' is an identifier but repeats "
                           f"{total_rows - profile['unique']:,} times.",
            })
        if profile["dtype"] == NUMERIC and profile.get("outlier_pct", 0) >= 5:
            findings.append({
                "id": f"outliers:{name}", "level": "info", "column": name,
                "rows": profile.get("outliers"),
                "message": f"{profile['outliers']:,} outliers in '{name}' "
                           f"({profile['outlier_pct']:.1f}%) outside 1.5×IQR.",
            })

    return findings


def _correlations(df: pd.DataFrame, profiles: list[dict]) -> list[dict]:
    numeric = [
        p["name"] for p in profiles
        if p["dtype"] == NUMERIC and "constant" not in p["flags"] and p["unique"] > 2
    ]
    if len(numeric) < 2:
        return []
    sample = df[numeric].head(MAX_CORRELATION_ROWS).apply(coerce_numeric)
    matrix = sample.corr(numeric_only=True).abs()
    pairs: list[dict] = []
    for i, left in enumerate(numeric):
        for right in numeric[i + 1:]:
            value = matrix.loc[left, right]
            if pd.isna(value) or value < 0.5:
                continue
            pairs.append({
                "a": left,
                "b": right,
                "r": round(float(sample[left].corr(sample[right])), 3),
                "strength": "strong" if value >= 0.7 else "moderate",
            })
    return sorted(pairs, key=lambda item: abs(item["r"]), reverse=True)[:8]


def profile_dataframe(df: pd.DataFrame) -> dict:
    """Full profile: columns, quality findings, time coverage and associations."""
    df = df.copy()
    df.columns = [str(column) for column in df.columns]
    profiles = [profile_column(df[column], column) for column in df.columns]

    duplicate_rows = int(df.duplicated().sum())
    total_cells = max(1, len(df) * max(1, len(df.columns)))
    missing_cells = int(df.isna().sum().sum())

    time_columns = [p for p in profiles if p["dtype"] == DATETIME]
    time_coverage = None
    if time_columns:
        best = max(time_columns, key=lambda p: p["unique"])
        coverage = detect_frequency(df[best["name"]])
        if coverage:
            time_coverage = {"column": best["name"], **coverage}

    counts = {NUMERIC: 0, CATEGORICAL: 0, DATETIME: 0, IDENTIFIER: 0, TEXT: 0, BOOLEAN: 0}
    for profile in profiles:
        counts[profile["dtype"]] = counts.get(profile["dtype"], 0) + 1

    return {
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "duplicate_rows": duplicate_rows,
        "duplicate_pct": round(duplicate_rows / len(df) * 100, 2) if len(df) else 0.0,
        "missing_cells": missing_cells,
        "missing_pct": round(missing_cells / total_cells * 100, 2),
        "type_counts": counts,
        "column_profiles": profiles,
        "quality": _quality_findings(profiles, df, duplicate_rows),
        "time_coverage": time_coverage,
        "correlations": _correlations(df, profiles),
        "sample": [
            {column: json_safe(value) for column, value in row.items()}
            for row in df.head(5).to_dict(orient="records")
        ],
    }


def column_tokens(name: str) -> set[str]:
    return set(tokens(name))


def numeric_columns(profile: dict, exclude: Optional[set[str]] = None) -> list[str]:
    exclude = exclude or set()
    return [
        column["name"]
        for column in profile["column_profiles"]
        if column["dtype"] == NUMERIC
        and column["unique"] > 2
        and "identifier" not in column["flags"]
        and column["name"] not in exclude
    ]


def datetime_columns(profile: dict) -> list[str]:
    return [column["name"] for column in profile["column_profiles"] if column["dtype"] == DATETIME]
