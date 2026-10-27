"""
Dataset understanding.

Scores the uploaded table against every supported analysis template using the
columns that actually map to each template's fields, then recommends analytical
tasks from the real value profiles. A weak or ambiguous result falls back to
general exploratory analysis instead of forcing a domain.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from services.mapping import suggest_mapping
from services.profiling import numeric_columns
from services.schemas import (
    CATEGORICAL,
    CHURN,
    DATETIME,
    FINANCIAL,
    GENERIC,
    HR,
    INVENTORY,
    MARKETING,
    NUMERIC,
    SALES,
    SCHEMAS,
    DatasetSchema,
)
from services.semantics import normalize

DOMAIN_SCHEMAS: tuple[DatasetSchema, ...] = (SALES, CHURN, INVENTORY, FINANCIAL, MARKETING, HR)
CLASSIFICATION_THRESHOLD = 0.42

TARGET_NAME_SIGNALS = (
    "churn", "churned", "attrition", "exited", "resigned", "cancelled",
    "canceled", "converted", "target", "label", "outcome", "default",
    "fraud", "is_active", "retained",
)
REGRESSION_NAME_SIGNALS = (
    "sales", "revenue", "amount", "price", "charges", "salary", "income",
    "profit", "score", "spend", "cost", "demand", "units_sold", "units",
)


def _matched_fields(decisions: dict[str, dict]) -> list[dict]:
    return [
        decision for decision in decisions.values()
        if decision["status"] in ("auto", "needs_review", "derived")
    ]


def _strong_fields(decisions: dict[str, dict]) -> list[dict]:
    return [
        decision for decision in decisions.values()
        if decision["status"] in ("auto", "derived")
    ]


def _schema_score(schema: DatasetSchema, decisions: dict[str, dict]) -> dict:
    fields = schema.fields or []
    matched = _matched_fields(decisions)
    strong = _strong_fields(decisions)
    required = schema.required_fields()
    required_hit = [
        spec for spec in required
        if decisions.get(spec.key, {}).get("status") in ("auto", "needs_review", "derived")
    ]
    targets = [spec for spec in fields if spec.target]
    target_hit = [
        spec for spec in targets
        if decisions.get(spec.key, {}).get("status") in ("auto", "needs_review")
    ]

    hits = len(matched)
    strong_hits = len(strong)
    weighted_hits = sum(
        1.0 if decision["status"] in ("auto", "derived") else 0.5
        for decision in matched
    )
    required_ratio = len(required_hit) / len(required) if required else 0.0

    score = (
        0.55 * min(1.0, weighted_hits / 9)
        + 0.25 * min(1.0, strong_hits / 5)
        + 0.12 * required_ratio
        + 0.08 * (1.0 if target_hit else 0.0)
    )
    # A template must earn its place; partial single-column matches are weak.
    if hits <= 2:
        score *= 0.6

    return {
        "schema": schema.id,
        "label": schema.label,
        "score": round(score, 4),
        "hits": hits,
        "strong_hits": strong_hits,
        "fields": len(fields),
        "matched": [decision["field"] for decision in matched],
        "strong_columns": [decision["column"] for decision in strong if decision["column"]],
        "required_present": [spec.key for spec in required_hit],
        "required_missing": [spec.key for spec in required if spec not in required_hit],
        "target_hit": target_hit[0].key if target_hit else None,
        "target_column": decisions.get(target_hit[0].key, {}).get("column") if target_hit else None,
        "decisions": decisions,
    }


def detect_targets(profile: dict) -> list[dict]:
    """Candidate supervised targets, with the reason they were suggested."""
    candidates: list[dict] = []
    for column in profile["column_profiles"]:
        name = normalize(column["name"])
        dtype = column["dtype"]
        if dtype == DATETIME or "identifier" in column["flags"]:
            continue
        unique = column["unique"]

        signal = next((word for word in TARGET_NAME_SIGNALS if word in name), None)
        if signal and 2 <= unique <= 30:
            candidates.append({
                "column": column["name"],
                "task": "classification",
                "classes": unique,
                "reason": f"column name contains '{signal}' and has {unique} distinct values",
                "priority": 1,
            })
            continue

        binary = dtype == "boolean" or (unique == 2 and column["unique_ratio"] <= 0.5)
        if binary and column["missing_pct"] < 50:
            candidates.append({
                "column": column["name"],
                "task": "classification",
                "classes": unique,
                "reason": "binary column (two outcomes)",
                "priority": 3,
            })
            continue

        measure_signal = next((word for word in REGRESSION_NAME_SIGNALS if word in name), None)
        if dtype == NUMERIC and measure_signal and unique > 10:
            candidates.append({
                "column": column["name"],
                "task": "regression",
                "classes": None,
                "reason": f"continuous measure ('{measure_signal}') with {unique:,} distinct values",
                "priority": 3,
            })

        # Any categorical with a limited label set can be modelled as an
        # outcome, even when its name gives no hint. Offered as a low-priority
        # option so the user decides, never auto-selected.
        if (
            dtype in (CATEGORICAL, "boolean")
            and 2 <= unique <= 20
            and column["missing_pct"] < 50
        ):
            candidates.append({
                "column": column["name"],
                "task": "classification",
                "classes": unique,
                "reason": f"categorical column with {unique} classes",
                "priority": 4,
            })

        if dtype == NUMERIC and unique > 10:
            candidates.append({
                "column": column["name"],
                "task": "regression",
                "classes": None,
                "reason": "continuous numeric column",
                "priority": 5,
            })

    deduped: dict[tuple[str, str], dict] = {}
    for candidate in candidates:
        key = (candidate["column"], candidate["task"])
        if key not in deduped or candidate["priority"] < deduped[key]["priority"]:
            deduped[key] = candidate
    return sorted(
        deduped.values(), key=lambda item: (item["priority"], item["column"])
    )[:8]


def _task_support(profile: dict, targets: list[dict]) -> dict:
    rows = profile["rows"]
    numeric = numeric_columns(profile)
    time = profile.get("time_coverage")
    classification = next((t for t in targets if t["task"] == "classification"), None)
    regression = next((t for t in targets if t["task"] == "regression"), None)

    forecast_reasons: list[str] = []
    forecast_ok = bool(time and numeric and rows >= 12)
    if not time:
        forecast_reasons.append("no parseable date column")
    elif time.get("periods", 0) < 3:
        forecast_reasons.append(f"only {time.get('periods', 0)} distinct periods")
    elif time.get("coverage", 1) < 0.5:
        # Must match services.validation.forecast_readiness, otherwise the task is
        # offered here and then rejected by validation on the same file.
        forecast_reasons.append(f"timeline coverage is {time['coverage'] * 100:.0f}% — large gaps")
        forecast_ok = False
    if not numeric:
        forecast_reasons.append("no numeric measure to forecast")
    if rows < 12:
        forecast_reasons.append(f"only {rows} rows")
    if forecast_reasons:
        forecast_ok = False

    return {
        "eda": {
            "available": rows > 0,
            "reason": "profiling and distributions always run" if rows else "no data rows",
        },
        "clustering": {
            "available": rows >= 30 and len(numeric) >= 2,
            "reason": (
                f"{len(numeric)} numeric features across {rows:,} rows"
                if rows >= 30 and len(numeric) >= 2
                else "needs at least 30 rows and 2 numeric columns"
            ),
        },
        "classification": {
            "available": rows >= 30 and classification is not None,
            "reason": (
                classification["reason"]
                if classification
                else "no binary or categorical outcome column found"
            ),
            "target": classification["column"] if classification else None,
        },
        "regression": {
            "available": rows >= 30 and regression is not None,
            "reason": (
                regression["reason"]
                if regression
                else "no continuous target column found"
            ),
            "target": regression["column"] if regression else None,
        },
        "forecast": {
            "available": bool(forecast_ok),
            "reason": (
                f"date coverage: {time['frequency']}, {time['periods']} periods"
                if forecast_ok else "; ".join(forecast_reasons) or "insufficient history"
            ),
            "time_column": time["column"] if time else None,
        },
    }


def _reasons_for(best: dict, profile: dict, schema: DatasetSchema) -> list[str]:
    reasons: list[str] = []
    examples = [column for column in best["strong_columns"] if column][:6]
    reasons.append(
        f"{best['hits']} of {best['fields']} template fields matched"
        + (f" ({', '.join(examples)})" if examples else "")
    )
    if best["required_present"]:
        reasons.append("required fields present: " + ", ".join(best["required_present"]))
    if best["required_missing"]:
        reasons.append("missing required fields: " + ", ".join(best["required_missing"]))
    if best["target_column"]:
        reasons.append(f"outcome column detected: '{best['target_column']}'")

    time_coverage = profile.get("time_coverage")
    if time_coverage and any(spec.role == "time" for spec in schema.fields):
        reasons.append(
            f"{time_coverage['column']} covers {time_coverage['from']} → {time_coverage['to']} "
            f"({time_coverage['frequency']}, {time_coverage['periods']} periods)"
        )
    return reasons


def classify_dataset(df: pd.DataFrame, profile: dict) -> dict:
    """Classify the table and recommend the analyses that are actually supported."""
    evaluations = []
    for schema in DOMAIN_SCHEMAS:
        decisions = suggest_mapping(df, profile, schema)
        evaluations.append(_schema_score(schema, decisions))

    evaluations.sort(key=lambda item: item["score"], reverse=True)
    best = evaluations[0]
    second = evaluations[1] if len(evaluations) > 1 else {"score": 0.0, "label": ""}
    targets = detect_targets(profile)
    supported = _task_support(profile, targets)

    if (
        best["score"] < CLASSIFICATION_THRESHOLD
        or best["hits"] < 3
        or best["strong_hits"] < 2
    ):
        return {
            "schema": GENERIC.id,
            "label": GENERIC.label,
            "description": GENERIC.description,
            "confidence": 0,
            "ambiguous": True,
            "score": best["score"],
            "reasons": [
                "No domain template matched strongly enough to classify this file.",
                "General exploratory analysis will be used so nothing is forced into an unrelated template.",
            ],
            "alternatives": [
                {"schema": evaluation["schema"], "label": evaluation["label"], "score": evaluation["score"]}
                for evaluation in evaluations[:3] if evaluation["score"] > 0
            ],
            "targets": targets,
            "supported_tasks": supported,
            "mapping": suggest_mapping(df, profile, GENERIC),
            "detected_target": None,
        }

    separation = best["score"] - second["score"]
    confidence = min(0.98, 0.5 * best["score"] + 0.5 * max(0.0, separation) + 0.25 * best["score"])
    confidence = round(confidence * 100)
    schema = SCHEMAS[best["schema"]]

    return {
        "schema": schema.id,
        "label": schema.label,
        "description": schema.description,
        "confidence": confidence,
        "ambiguous": confidence < 55,
        "score": best["score"],
        "reasons": _reasons_for(best, profile, schema),
        "alternatives": [
            {"schema": evaluation["schema"], "label": evaluation["label"], "score": evaluation["score"]}
            for evaluation in evaluations[1:4]
            if evaluation["score"] >= 0.2
        ],
        "targets": targets,
        "supported_tasks": supported,
        "mapping": best["decisions"],
        "detected_target": best["target_column"],
    }


def resolve_task(
    schema: DatasetSchema,
    profile: dict,
    requested_task: Optional[str],
    requested_target: Optional[str] = None,
) -> dict:
    """Pick the analysis task honestly: requested, schema default, or EDA."""
    targets = detect_targets(profile)
    supported = _task_support(profile, targets)
    # A schema target key is a canonical name (e.g. 'churn_status') that may not
    # exist as a source column, so only use it when the file really has it.
    schema_target = next((spec for spec in schema.fields if spec.target), None)
    profile_columns = {column["name"] for column in profile["column_profiles"]}
    schema_default = schema.default_target if schema.default_target in profile_columns else None
    default_target = (
        schema_default
        or (targets[0]["column"] if targets else None)
        or (schema_target.key if schema_target else None)
    )
    task = (requested_task or schema.default_task or "eda").lower()
    if task not in supported:
        task = "eda"
    if not supported.get(task, {}).get("available", task == "eda"):
        task = "eda"
    return {
        "task": task,
        "target": requested_target or default_target,
        "supported_tasks": supported,
        "target_candidates": targets,
    }
