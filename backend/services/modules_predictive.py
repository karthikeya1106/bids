"""
Predictive modules: Forecast & Strategy.

Forecast shows a time-series projection only when a date column and a numeric
measure exist; otherwise, for a confirmed outcome column, it shows a supervised
model evaluated on a held-out split. Strategy converts measured associations
into prioritised actions and labels every estimate as association-based.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from services.adaptive import classify, forecast, regress
from services.semantics import humanize
from services.stats_lib import (
    band_table,
    bar_section,
    card,
    categorical_driver,
    class_display,
    event_mask,
    line_section,
    module_payload,
    notice_section,
    num,
    numeric_driver,
    p_display,
    payoff_section,
    rate_label,
    table_section,
    usable_dimensions,
    usable_measures,
)

MONEY_HINTS = ("bill", "charge", "revenue", "sales", "amount", "price", "spend", "cost", "income", "profit")
USAGE_HINTS = ("download", "upload", "usage", "minutes", "mins", "calls")


def _forecast_measure(caps: dict, frame: pd.DataFrame) -> Optional[str]:
    candidates = usable_measures(caps, frame)
    ranked = sorted(
        candidates,
        key=lambda column: (
            0 if any(hint in column.lower() for hint in MONEY_HINTS)
            else 1 if any(hint in column.lower() for hint in USAGE_HINTS)
            else 2
        ),
    )
    for column in ranked:
        if frame[column].dropna().astype(float).nunique() > 5:
            return column
    return candidates[0] if candidates else None


def _time_series(frame: pd.DataFrame, caps: dict) -> dict:
    time_column = caps["time_coverage"]["column"]
    measure = _forecast_measure(caps, frame)
    if measure is None:
        return module_payload(
            "forecast", caps, "unavailable",
            requires=["A numeric measure column"],
            sections=[notice_section("no-measure", "No numeric measure", "The dataset has a date column but no numeric measure to forecast.", tone="warning")],
        )

    result = forecast(frame, time_column, measure)
    if not result.get("available", True):
        return module_payload(
            "forecast",
            caps,
            "partial",
            sections=[notice_section(
                "forecast-unavailable",
                "Forecast not available",
                " ".join(result.get("notes", ["The series does not have enough history for a reliable forecast."])),
                tone="warning",
            )],
            requires=["At least 12 dated observations across 8 complete periods"],
            limitations=result.get("notes", []),
        )

    metrics = result.get("metrics", {})
    summary = [
        card("Model", result.get("method", "—"), "text"),
        card("Frequency", result.get("frequency", "—").upper(), "text"),
        card("Holdout MAE", metrics.get("mae"), "decimal"),
        card("Holdout MAPE", metrics.get("mape"), "percent"),
        card("Naïve MAE", metrics.get("naive_mae"), "decimal", hint="last-value baseline on the same holdout"),
    ]

    history = result.get("history", [])
    forecast_rows = result.get("forecast", [])
    data = []
    for row in history:
        data.append({"period": row["period"], "actual": row["value"], "forecast": None, "lower": None, "upper": None})
    for row in forecast_rows:
        data.append({"period": row["period"], "actual": None, "forecast": row["value"], "lower": row.get("lower"), "upper": row.get("upper")})

    sections = [
        line_section(
            "forecast-series",
            f"{humanize(measure)}: history and projection",
            data,
            ["actual", "forecast"],
            description=f"History aggregated by {result.get('frequency')} period, with a {len(forecast_rows)}-period projection and 95% intervals.",
            note="Intervals widen with the horizon and assume the recent pattern continues.",
        ),
        table_section(
            "forecast-table",
            "Projected periods",
            [
                {"key": "period", "label": "Period"},
                {"key": "value", "label": "Forecast", "format": "decimal", "align": "right"},
                {"key": "lower", "label": "Lower 95%", "format": "decimal", "align": "right"},
                {"key": "upper", "label": "Upper 95%", "format": "decimal", "align": "right"},
            ],
            forecast_rows,
            description="Point forecast and interval bounds for each future period.",
        ),
    ]

    return module_payload(
        "forecast",
        caps,
        "ready",
        summary=summary,
        sections=sections,
        limitations=result.get("notes", []) + [
            "The projection is a statistical extrapolation of one measure, not a business plan.",
        ],
        method=result.get("method"),
    )


def _prediction(frame: pd.DataFrame, caps: dict, target: dict) -> dict:
    measures = usable_measures(caps, frame)
    dimensions = usable_dimensions(caps, frame)
    event, valid, event_name = event_mask(frame, target)

    if target.get("kind") == "continuous":
        result = regress(frame, target["column"], measures, dimensions)
        if not result.get("available", True):
            return module_payload(
                "forecast", caps, "partial",
                sections=[notice_section("model-unavailable", "Model not available", " ".join(result.get("notes", [])), tone="warning")],
                requires=result.get("notes", []),
            )
        metrics = result.get("metrics", {})
        summary = [
            card("Task", "Regression", "text"),
            card("Model", result.get("selected_model", "—"), "text"),
            card("R² (holdout)", metrics.get("r2"), "decimal"),
            card("MAE (holdout)", metrics.get("mae"), "decimal"),
            card("Baseline MAE", result.get("baseline", {}).get("mae"), "decimal", hint="predict-the-mean baseline"),
        ]
        importances = result.get("importances", [])
        sections = []
        if importances:
            sections.append(bar_section(
                "importances",
                "Feature importance",
                [{"label": humanize(row["feature"]), "value": row["importance"]} for row in importances],
                description="Relative contribution in the selected model.",
                kind="decimal",
                note="Importance is association inside the model, not a causal effect.",
            ))
        return module_payload(
            "forecast", caps, "ready", summary=summary, sections=sections,
            limitations=result.get("notes", []), method=result.get("method"),
        )

    result = classify(frame, target["column"], measures, dimensions, event_label=target.get("event"))
    if not result.get("available", True):
        return module_payload(
            "forecast",
            caps,
            "partial",
            summary=[card("Target", target["column"], "text"), card("Classes", len(result.get("classes", [])), "number")],
            sections=[notice_section(
                "model-unavailable",
                "Prediction not available",
                " ".join(result.get("notes", ["The target does not support supervised learning."])),
                tone="warning",
            )],
            requires=result.get("notes", []),
        )

    metrics = result.get("metrics", {})
    baseline = result.get("baseline", {})
    summary = [
        card("Task", "Classification", "text"),
        card("Model", result.get("selected_model", "—"), "text"),
        card("Accuracy (holdout)", metrics.get("accuracy"), "percent"),
        card("Balanced accuracy", metrics.get("balanced_accuracy"), "percent", hint="fairer when classes are imbalanced"),
        card("F1 (macro)", metrics.get("f1_macro"), "decimal"),
        card("ROC-AUC", metrics.get("roc_auc"), "decimal"),
        card("Baseline accuracy", baseline.get("accuracy"), "percent", hint="most-frequent-class baseline"),
    ]

    sections: list[dict] = []
    confusion = result.get("confusion", {})
    if confusion.get("matrix"):
        labels = [class_display(target["column"], label) for label in confusion.get("labels", [])]
        sections.append(payoff_section(
            "confusion",
            "Confusion matrix (holdout)",
            labels,
            confusion["matrix"],
            description="Rows are observed classes, columns are predicted classes, on the 25% holdout split.",
        ))

    importances = result.get("importances", [])
    if importances:
        sections.append(bar_section(
            "importances",
            "Feature importance",
            [{"label": humanize(row["feature"]), "value": row["importance"]} for row in importances],
            description="Relative contribution of each feature in the selected model.",
            kind="decimal",
            note="Importance shows how the model uses a feature; it does not prove the feature causes the outcome.",
        ))

    bands = result.get("probability_bands", [])
    if bands:
        sections.append(bar_section(
            "risk-bands",
            f"Predicted {event_name.lower()} probability bands (holdout)",
            [
                {"label": row["band"], "value": row["count"], "secondary": f"{row['observed_rate']}% observed {event_name.lower()}"}
                for row in bands
            ],
            description="Holdout rows grouped by predicted probability, with the observed outcome rate in each band.",
            kind="number",
            note="A well-calibrated model shows a rising observed rate across the bands.",
        ))

    comparison = result.get("comparison", [])
    if comparison:
        sections.append(table_section(
            "model-comparison",
            "Candidate models (cross-validation)",
            [
                {"key": "model", "label": "Model"},
                {"key": "cv_f1_macro", "label": "CV macro-F1", "format": "decimal", "align": "right"},
                {"key": "cv_std", "label": "Std", "format": "decimal", "align": "right"},
            ],
            [row for row in comparison if row.get("cv_f1_macro") is not None],
            description="Mean macro-F1 over stratified folds of the training split. The best model is refitted and scored on the holdout.",
        ))

    split = result.get("split", {})
    sections.append(notice_section(
        "split-note",
        "How this was evaluated",
        f"{result.get('method')}. Training rows: {split.get('train_rows', 0):,}; holdout rows: {split.get('test_rows', 0):,}. "
        "The target column and identifier columns were excluded from the predictors.",
        tone="info",
    ))

    return module_payload(
        "forecast",
        caps,
        "ready",
        summary=summary,
        sections=sections,
        insights=[
            {
                "title": f"Measured holdout performance for {event_name.lower()} prediction",
                "detail": (
                    f"{result.get('selected_model')} reaches {metrics.get('balanced_accuracy')} balanced accuracy "
                    f"and {metrics.get('roc_auc')} ROC-AUC, versus {baseline.get('accuracy')} accuracy for always predicting the majority class."
                ),
                "tone": "info",
            }
        ] if metrics.get("balanced_accuracy") is not None else [],
        limitations=result.get("notes", []) + [
            "Metrics come from one holdout split of this file; performance on new data may differ.",
            "Predictions describe association, not the effect of an intervention.",
        ],
        method=result.get("method"),
    )


def forecast_module(frame: pd.DataFrame, caps: dict) -> dict:
    module = caps["modules"]["forecast"]
    target = caps.get("target")
    mode = module.get("forecast_mode")

    if mode == "time_series":
        return _time_series(frame, caps)
    if mode == "prediction" and target and target.get("confirmed"):
        result = _prediction(frame, caps, target)
        # Prediction mode is only selected when there is no usable time axis, so
        # say plainly that nothing was projected into the future.
        result.setdefault("limitations", []).append(
            "No future projection was produced: this dataset has no usable date column, "
            "so the model scores the rows that exist instead of forecasting new periods."
        )
        return result
    if mode == "prediction" and target:
        return module_payload(
            "forecast",
            caps,
            "partial",
            summary=[card("Rows", len(frame), "number"), card("Suggested target", target["column"], "text")],
            sections=[
                notice_section(
                    "confirm-target",
                    "Confirm the outcome column to run a model",
                    f"'{target['column']}' has {len(target.get('classes', []))} observed classes and looks like an outcome. "
                    "It is only a suggestion, so no model has been trained. Confirm it in the Analysis Report to evaluate a classifier.",
                    tone="info",
                ),
                notice_section(
                    "no-time-dimension",
                    "No time-series forecast is possible",
                    "This dataset contains no parseable date column, so a future projection cannot be produced. Only a scoring model on the existing rows is supported.",
                    tone="info",
                ),
            ],
            requires=["Confirm a prediction target"],
            limitations=["Nothing is forecast until a target is confirmed or a date column is added."],
        )

    return module_payload(
        "forecast",
        caps,
        "unavailable",
        sections=[notice_section(
            "no-forecast-inputs",
            "This dataset cannot support forecasting",
            "A forecast needs either a date column with at least 12 observations and a numeric measure, or a confirmed outcome column for prediction.",
            tone="warning",
        )],
        requires=module.get("requires", []),
        limitations=["No forecast or prediction is shown because the required inputs are absent."],
    )


# ─── Strategy ───────────────────────────────────────────────────────────────

def strategy_module(frame: pd.DataFrame, caps: dict) -> dict:
    target = caps.get("target")
    measures = usable_measures(caps, frame)
    dimensions = usable_dimensions(caps, frame)
    event, valid, event_name = event_mask(frame, target)
    reference_name = next(
        (class_display(target["column"], entry["label"]) for entry in (target or {}).get("classes", []) if str(entry["label"]) != str((target or {}).get("event"))),
        "Other",
    )

    if not target:
        correlations = []
        from services.stats_lib import correlation_rows

        correlations = correlation_rows(frame, measures, limit=6)
        return module_payload(
            "strategy",
            caps,
            "partial",
            summary=[card("Rows", len(frame), "number"), card("Measures", len(measures), "number")],
            sections=[
                notice_section(
                    "needs-outcome",
                    "No outcome to prioritise against",
                    "Strategy actions are prioritised by their measured effect on an outcome. This dataset has no outcome column, so only descriptive relationships can be reported.",
                    tone="warning",
                ),
                table_section(
                    "correlations",
                    "Measured relationships",
                    [
                        {"key": "a", "label": "Measure A"},
                        {"key": "b", "label": "Measure B"},
                        {"key": "r", "label": "Pearson r", "format": "decimal", "align": "right"},
                        {"key": "strength", "label": "Strength"},
                    ],
                    correlations,
                ) if correlations else notice_section("none", "No relationships", "No numeric relationship could be measured.", tone="info"),
            ],
            requires=["An outcome column (e.g. churn) to measure an effect against"],
            limitations=["No actionable opportunity can be quantified without an outcome."],
        )

    drivers = []
    if target.get("kind") == "binary":
        for column in measures:
            driver = numeric_driver(frame, column, event, valid, event_name, reference_name)
            if driver:
                drivers.append(driver)
        for column in dimensions:
            driver = categorical_driver(frame, column, event, valid, event_name)
            if driver:
                drivers.append(driver)
    drivers.sort(key=lambda row: abs(row["effect"] or 0), reverse=True)

    # Two strongly correlated measures describe the same signal; keeping both
    # would double-count the same accounts in the action list.
    deduped = []
    for driver in drivers:
        if driver["type"] == "numeric":
            column = driver["factor"]
            redundant = False
            for kept in deduped:
                if kept["type"] != "numeric" or kept["factor"] not in frame.columns:
                    continue
                try:
                    correlation = frame[column].corr(frame[kept["factor"]])
                except (TypeError, ValueError):
                    correlation = None
                if correlation is not None and abs(float(correlation)) >= 0.85:
                    redundant = True
                    break
            if redundant:
                continue
        deduped.append(driver)
    drivers = deduped

    threshold = 0.05 / max(1, len(drivers))

    baseline = float(target.get("event_share") or 0.0)
    plays = []
    for driver in drivers:
        if driver.get("p_value") is None or driver["p_value"] > threshold:
            continue
        if abs(driver["effect"] or 0) < 0.1:
            continue

        group_label = None
        group_n = 0
        group_rate = None
        if driver["type"] == "categorical":
            levels = [level for level in driver.get("levels", []) if level["n"] >= 30 and level["rate"] is not None]
            if not levels:
                continue
            worst = max(levels, key=lambda level: level["rate"])
            group_label, group_n, group_rate = worst["level"], worst["n"], worst["rate"]
        else:
            bands = [
                row for row in band_table(frame, driver["factor"], event, valid, event_name)
                if row["n"] >= 30 and row["rate"] is not None
            ]
            if not bands:
                continue
            worst = max(bands, key=lambda row: row["rate"])
            group_label, group_n, group_rate = worst["band"], worst["n"], worst["rate"]

        gap = round(group_rate - baseline, 2)
        if gap <= 0.5:
            continue
        excess = int(round(group_n * gap / 100))
        plays.append({
            "factor": driver["label"],
            "group": group_label,
            "n": int(group_n),
            "rate": group_rate,
            "baseline_rate": baseline,
            "gap_pp": gap,
            "excess_events": excess,
            "effect": driver["effect"],
            "effect_label": driver.get("effect_label"),
            "evidence": driver["evidence"],
            "priority": "P1" if gap >= 5 else "P2",
            "confidence": "Association-based",
        })

    plays.sort(key=lambda row: row["excess_events"], reverse=True)
    plays = plays[:6]
    largest_gap = plays[0]["excess_events"] if plays else 0

    summary = [
        card("Prioritised actions", len(plays), "number"),
        card(f"Largest {event_name.lower()} gap", largest_gap, "number", hint="accounts above the overall rate in one group"),
        card(rate_label(event_name), baseline, "percent"),
        card("Factors screened", len(drivers), "number", hint=f"Bonferroni α = {threshold:.2e}"),
    ]

    sections: list[dict] = []
    if plays:
        sections.append(table_section(
            "plays",
            "Prioritised actions",
            [
                {"key": "priority", "label": "Priority"},
                {"key": "factor", "label": "Factor"},
                {"key": "group", "label": "Group"},
                {"key": "n", "label": "Accounts", "format": "number", "align": "right"},
                {"key": "rate", "label": "Observed rate", "format": "percent", "align": "right"},
                {"key": "baseline_rate", "label": "Overall", "format": "percent", "align": "right"},
                {"key": "gap_pp", "label": "Gap", "format": "decimal", "align": "right"},
                {"key": "excess_events", "label": f"Excess {event_name.lower()}", "format": "number", "align": "right"},
            ],
            plays,
            description="Groups where the observed outcome rate is materially above the overall rate. Accounts are counted, not extrapolated.",
            note="Excess events = accounts × (group rate − overall rate). This is a measured gap, not a savings forecast.",
        ))
        sections.append(bar_section(
            "excess",
            f"Excess {event_name.lower()} events by factor",
            [{"label": f"{row['factor']}: {row['group']}"[:60], "value": row["excess_events"]} for row in plays],
            description="Size of the measured gap in accounts, for ranking only.",
            kind="number",
        ))
        actions = []
        for index, row in enumerate(plays, start=1):
            actions.append({
                "priority": row["priority"],
                "area": row["factor"],
                "action": (
                    f"Investigate {row['factor'].lower()} = {row['group']}: {row['rate']}% {event_name.lower()} "
                    f"versus {baseline}% overall across {row['n']:,} accounts."
                ),
                "affected": row["n"],
                "evidence": row["evidence"],
                "confidence": row["confidence"],
            })
        sections.append(table_section(
            "action-list",
            "Recommended actions",
            [
                {"key": "priority", "label": "Priority"},
                {"key": "area", "label": "Area"},
                {"key": "action", "label": "Action"},
                {"key": "affected", "label": "Accounts", "format": "number", "align": "right"},
            ],
            actions,
            description="Each action points at a measured gap. Validate with a controlled pilot before committing resources.",
        ))
    else:
        sections.append(notice_section(
            "no-plays",
            "No material gap found",
            "No factor showed a statistically supported gap above the overall outcome rate, so no action is recommended from this file.",
            tone="info",
        ))

    if target.get("kind") != "binary":
        limitations_extra = ["This dataset has more than two outcome classes; the strategy view expects a binary outcome."]
    else:
        limitations_extra = []

    return module_payload(
        "strategy",
        caps,
        "ready",
        summary=summary,
        sections=sections,
        insights=[
            {
                "title": f"{plays[0]['factor']} is the largest measured opportunity",
                "detail": (
                    f"{plays[0]['n']:,} accounts in '{plays[0]['group']}' show a {plays[0]['rate']}% {event_name.lower()} rate "
                    f"versus {baseline}% overall ({plays[0]['excess_events']:,} excess events)."
                ),
                "tone": "warning",
            }
        ] if plays else [],
        limitations=limitations_extra + ([target["polarity"]] if target.get("polarity") else []) + [
            "Opportunities are association-based gaps; they do not prove that changing the factor reduces churn.",
            "No monetary value is attached because it would require assumptions this dataset does not contain.",
            "Validate any action with a controlled pilot before committing resources.",
        ],
        method="Ranked outcome-rate gaps with Bonferroni-corrected significance",
    )
