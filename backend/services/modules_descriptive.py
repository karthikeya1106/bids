"""
Descriptive modules: Executive Dashboard, Behavior Analytics, Customer Segments.

These three only report what is measured in the committed rows. A sales-only
revenue metric is never invented for a churn or generic dataset; instead the
dashboard shows record counts, the observed outcome split, measure comparisons
and the data-quality findings that affect them.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from services.adaptive import cluster
from services.semantics import humanize
from services.stats_lib import (
    band_table,
    bar_section,
    card,
    categorical_driver,
    class_display,
    correlation_rows,
    count,
    event_mask,
    fmt,
    grouped_histogram,
    histogram_section,
    module_payload,
    notice_section,
    num,
    numeric_driver,
    p_display,
    rate_label,
    strength_label,
    table_section,
    top_dimension_signal,
    usable_dimensions,
    usable_measures,
)

MONEY_HINTS = ("bill", "charge", "revenue", "sales", "amount", "price", "spend", "cost", "income", "profit")
TENURE_HINTS = ("tenure", "subscription_age", "account_age", "lifetime", "months")
USAGE_HINTS = ("download", "upload", "usage", "minutes", "mins", "calls", "messages")


def _measure_priority(column: str) -> int:
    name = column.lower()
    if any(hint in name for hint in MONEY_HINTS):
        return 0
    if any(hint in name for hint in TENURE_HINTS):
        return 1
    if any(hint in name for hint in USAGE_HINTS):
        return 2
    return 3


def _measure_label(column: str) -> str:
    name = column.lower()
    base = column
    if name.endswith("_avg") or name.endswith("_mean"):
        base = column[: -4]
        label = humanize(base)
        return f"Average {label}"
    return humanize(column)


def _event_count(target: Optional[dict]) -> Optional[int]:
    if not target or not target.get("event"):
        return None
    for entry in target.get("classes", []):
        if str(entry["label"]) == str(target["event"]):
            return int(entry["count"])
    return None


def _class_pair(target: Optional[dict]) -> tuple[str, str]:
    if not target or not target.get("classes"):
        return "Yes", "No"
    labels = [str(entry["label"]) for entry in target["classes"]]
    event = str(target.get("event")) if target.get("event") is not None else labels[-1]
    other = next((label for label in labels if label != event), labels[0])
    return class_display(target["column"], event), class_display(target["column"], other)


def _outcome_sections(frame: pd.DataFrame, caps: dict) -> tuple[list[dict], list[dict], list[str]]:
    target = caps.get("target")
    sections: list[dict] = []
    insights: list[dict] = []
    limitations: list[str] = []
    if not target:
        sections.append(notice_section(
            "no-target",
            "No outcome column detected",
            "This dataset has no churn/attrition-style outcome column, so outcome rates cannot be computed. "
            "The measures and groupings below are the full descriptive view.",
            tone="info",
        ))
        return sections, insights, limitations

    event, valid, event_name = event_mask(frame, target)
    reference_name = next(
        (class_display(target["column"], entry["label"]) for entry in target["classes"] if str(entry["label"]) != str(target.get("event"))),
        "Other",
    )
    split = [
        {
            "label": class_display(target["column"], entry["label"]),
            "value": int(entry["count"]),
            "secondary": f"{entry['share']:.1f}%",
        }
        for entry in target.get("classes", [])
    ]
    sections.append(bar_section(
        "outcome-split",
        f"Observed {humanize(target['column'])} split",
        split,
        description="Counts of each observed outcome class in the committed rows.",
        kind="number",
        note=None if target.get("confirmed") else "This outcome column is detected from the data; confirm it in the Analysis Report before supervised modelling.",
    ))

    if not target.get("confirmed"):
        limitations.append(
            f"'{target['column']}' is currently a suggested outcome. Supervised prediction stays disabled until it is confirmed."
        )
    if target.get("polarity"):
        limitations.append(target["polarity"])

    dimensions = usable_dimensions(caps, frame, limit=3)
    rows: list[dict] = []
    drivers = top_dimension_signal(frame, dimensions, event, valid, event_name)
    for driver in drivers[:3]:
        for level in driver.get("levels", []):
            rows.append({
                "factor": driver["label"],
                "level": level["level"],
                "n": level["n"],
                "events": level["events"],
                "rate": level["rate"],
                "effect": driver["effect"],
                "p_value": p_display(driver["p_value"]),
            })
    if rows:
        sections.append(table_section(
            "outcome-by-group",
            f"{rate_label(event_name)} by grouping",
            [
                {"key": "factor", "label": "Factor"},
                {"key": "level", "label": "Group"},
                {"key": "n", "label": "Rows", "format": "number", "align": "right"},
                {"key": "events", "label": event_name, "format": "number", "align": "right"},
                {"key": "rate", "label": "Rate", "format": "percent", "align": "right"},
                {"key": "effect", "label": "Cramér's V", "format": "decimal", "align": "right"},
            ],
            rows,
            description=f"Measured {event_name.lower()} rate per group. The overall rate is the baseline.",
            note=f"Baseline: {target.get('event_share')}% {event_name.lower()} across {int(valid.sum()):,} rows.",
        ))
        strongest = drivers[0]
        insights.append({
            "title": f"{rate_label(event_name)} differs across {strongest['label']}",
            "detail": strongest["evidence"] + f" Overall rate {target.get('event_share')}%.",
            "tone": "warning" if abs(strongest["effect"] or 0) >= 0.1 else "info",
        })

    measures = sorted(usable_measures(caps, frame), key=_measure_priority)[:4]
    comparison_rows = []
    numeric_drivers = []
    for column in measures:
        driver = numeric_driver(frame, column, event, valid, event_name, reference_name)
        if not driver:
            continue
        numeric_drivers.append(driver)
        difference = None
        if driver["reference_mean"] not in (None, 0) and driver["group_mean"] is not None:
            difference = round((driver["group_mean"] - driver["reference_mean"]) / abs(driver["reference_mean"]) * 100, 2)
        comparison_rows.append({
            "factor": driver["label"],
            "event_mean": driver["group_mean"],
            "reference_mean": driver["reference_mean"],
            "difference_pct": difference,
            "p_value": p_display(driver["p_value"]),
        })
    if comparison_rows:
        sections.append(table_section(
            "measures-by-outcome",
            f"Measures by outcome ({event_name} vs {reference_name})",
            [
                {"key": "factor", "label": "Measure"},
                {"key": "event_mean", "label": event_name, "format": "decimal", "align": "right"},
                {"key": "reference_mean", "label": reference_name, "format": "decimal", "align": "right"},
                {"key": "difference_pct", "label": "Difference", "format": "percent", "align": "right"},
                {"key": "p_value", "label": "Mann-Whitney p", "align": "right"},
            ],
            comparison_rows,
            description="Mean value of each measure in each outcome group.",
            note="Difference is relative to the reference group. Small p-values indicate the groups differ; they do not prove the measure causes the outcome.",
        ))
        numeric_drivers.sort(key=lambda row: abs(row["effect"] or 0), reverse=True)
        if numeric_drivers:
            top = numeric_drivers[0]
            insights.append({
                "title": f"{top['label']} differs between outcome groups",
                "detail": (
                    f"{event_name} median {top['group_median']:,.2f} vs {reference_name} "
                    f"{top['reference_median']:,.2f} (p {p_display(top['p_value'])})."
                ),
                "tone": "warning" if abs(top["effect"] or 0) >= 0.1 else "info",
            })

    focus = None
    if measures:
        focus = max(
            measures,
            key=lambda column: next(
                (abs(driver["effect"] or 0) for driver in numeric_drivers if driver["factor"] == column),
                0.0,
            ),
        )
    if focus and event.any():
        groups = {reference_name: valid & ~event, event_name: event}
        bins, series = grouped_histogram(frame, focus, groups)
        if bins:
            sections.append(histogram_section(
                "distribution-by-outcome",
                f"{_measure_label(focus)} distribution by outcome",
                bins,
                series,
                description="Row counts per value range, split by the observed outcome.",
            ))
    return sections, insights, limitations


def _missing_table(frame: pd.DataFrame) -> Optional[dict]:
    missing = []
    for column in frame.columns:
        share = float(frame[column].isna().mean() * 100)
        if share > 0:
            missing.append({"column": humanize(column), "missing_pct": round(share, 2), "missing": int(frame[column].isna().sum())})
    if not missing:
        return None
    missing.sort(key=lambda row: row["missing_pct"], reverse=True)
    return table_section(
        "data-quality",
        "Missing values",
        [
            {"key": "column", "label": "Column"},
            {"key": "missing", "label": "Missing rows", "format": "number", "align": "right"},
            {"key": "missing_pct", "label": "Share", "format": "percent", "align": "right"},
        ],
        missing[:6],
        description="Columns with at least one empty cell. Missing values are not filled with zero in any calculation.",
        note="Measures are computed on the non-missing values of each column, so their row counts can differ.",
    )


def dashboard_module(frame: pd.DataFrame, caps: dict) -> dict:
    rows = int(len(frame))
    subjects = caps.get("subjects") or {}
    target = caps.get("target")
    summary = [card("Records", rows, "number", hint=f"{len(frame.columns)} columns")]
    if subjects.get("column"):
        summary.append(card(subjects.get("label", "Customers").title(), subjects.get("count", rows), "number", hint=f"distinct values of '{subjects['column']}'"))

    event, valid, event_name = event_mask(frame, target)
    if target and target.get("event_share") is not None:
        summary.append(card(rate_label(event_name), target["event_share"], "percent", hint=f"{target_classes_summary(target)}"))
        event_count = _event_count(target)
        if event_count is not None:
            summary.append(card(f"{event_name}", event_count, "number"))
            summary.append(card("Retained", rows - event_count, "number", hint="rows not in the observed event class"))

    measures = sorted(usable_measures(caps, frame), key=_measure_priority)
    for column in measures[:4]:
        series = frame[column].dropna().astype(float)
        if series.empty:
            continue
        kind = "currency" if _measure_priority(column) == 0 else "decimal"
        summary.append(card(_measure_label(column), series.mean(), kind, hint=f"median {series.median():,.2f}"))

    sections, insights, limitations = _outcome_sections(frame, caps)
    quality = _missing_table(frame)
    if quality:
        sections.append(quality)
        worst = quality["rows"][0]
        insights.append({
            "title": f"{worst['column']} is incomplete",
            "detail": f"{worst['missing_pct']}% of rows ({worst['missing']:,}) have no value. Analyses use the rows that do.",
            "tone": "warning" if worst["missing_pct"] >= 20 else "info",
        })

    if not caps.get("has_time"):
        limitations.append("No parseable date column, so trends, cohort retention and time-series forecasts are unavailable.")
    limitations.extend([
        "Every figure is computed from the committed rows of this dataset only.",
        "Group differences are associations; they do not establish causation.",
    ])

    return module_payload(
        "dashboard",
        caps,
        "ready" if rows else "unavailable",
        summary=summary,
        sections=sections,
        insights=insights,
        limitations=limitations,
        requires=[] if rows else ["Upload a dataset"],
    )


def target_classes_summary(target: dict) -> str:
    parts = [f"{class_display(target['column'], entry['label'])} {entry['count']:,}" for entry in target.get("classes", [])]
    return " · ".join(parts)


def behavior_module(frame: pd.DataFrame, caps: dict) -> dict:
    target = caps.get("target")
    measures = sorted(usable_measures(caps, frame), key=_measure_priority)
    dimensions = usable_dimensions(caps, frame)
    event, valid, event_name = event_mask(frame, target)
    reference_name = next(
        (class_display(target["column"], entry["label"]) for entry in (target or {}).get("classes", []) if str(entry["label"]) != str((target or {}).get("event"))),
        "Other",
    )

    sections: list[dict] = []
    insights: list[dict] = []
    limitations: list[str] = []
    summary: list[dict] = []

    if target:
        summary.append(card("Rows analysed", int(valid.sum()), "number"))
        summary.append(card(event_name, int(event.sum()), "number", hint=f"{target.get('event_share')}% of rows"))
        summary.append(card(reference_name, int((valid & ~event).sum()), "number"))
    else:
        summary.append(card("Rows analysed", len(frame), "number"))
    if measures:
        summary.append(card("Measures", len(measures), "number", hint="numeric columns used"))
    if dimensions:
        summary.append(card("Groupings", len(dimensions), "number", hint="binary / categorical columns"))

    if not target:
        sections.append(notice_section(
            "no-outcome",
            "Descriptive profiling only",
            "No outcome column was detected, so this page reports feature distributions and correlations instead of outcome comparisons.",
        ))

    if target:
        band_rows: list[dict] = []
        for column in measures[:3]:
            band_rows.extend(band_table(frame, column, event, valid, event_name))
        if band_rows:
            sections.append(table_section(
                "outcome-bands",
                f"{rate_label(event_name)} by value band",
                [
                    {"key": "factor", "label": "Measure"},
                    {"key": "band", "label": "Band"},
                    {"key": "n", "label": "Rows", "format": "number", "align": "right"},
                    {"key": "events", "label": event_name, "format": "number", "align": "right"},
                    {"key": "rate", "label": "Rate", "format": "percent", "align": "right"},
                ],
                band_rows,
                description="Each measure is split into equal-count bands; the outcome rate is measured inside each band.",
                note=f"Baseline {event_name.lower()} rate {target.get('event_share')}%.",
            ))

        numeric_drivers = []
        for column in measures:
            driver = numeric_driver(frame, column, event, valid, event_name, reference_name)
            if driver:
                numeric_drivers.append(driver)
        numeric_drivers.sort(key=lambda row: abs(row["effect"] or 0), reverse=True)
        if numeric_drivers:
            sections.append(bar_section(
                "numeric-association",
                "Numeric features ranked by association",
                [
                    {
                        "label": driver["label"],
                        "value": abs(driver["effect"] or 0),
                        "secondary": f"p {p_display(driver['p_value'])}",
                    }
                    for driver in numeric_drivers[:10]
                ],
                description="Absolute rank-biserial correlation between each measure and the observed outcome (0 = no association, 1 = complete separation).",
                kind="decimal",
            ))
            top = numeric_drivers[0]
            insights.append({
                "title": f"{top['label']} separates the outcome groups most strongly",
                "detail": (
                    f"{strength_label(top['effect'] or 0).title()} association: {event_name} median "
                    f"{top['group_median']:,.2f} vs {reference_name} {top['reference_median']:,.2f}."
                ),
                "tone": "warning" if abs(top["effect"] or 0) >= 0.1 else "info",
            })

        cat_drivers = top_dimension_signal(frame, dimensions, event, valid, event_name)
        if cat_drivers:
            sections.append(bar_section(
                "categorical-association",
                "Groupings ranked by association",
                [
                    {"label": driver["label"], "value": driver["effect"], "secondary": f"p {p_display(driver['p_value'])}"}
                    for driver in cat_drivers[:10]
                ],
                description="Cramér's V between each grouping column and the observed outcome (0 = independent).",
                kind="decimal",
            ))
            top = cat_drivers[0]
            insights.append({
                "title": f"{rate_label(event_name)} differs across {top['label']}",
                "detail": top["evidence"],
                "tone": "warning" if abs(top["effect"] or 0) >= 0.1 else "info",
            })

        if numeric_drivers:
            focus = numeric_drivers[0]["factor"]
            bins, series = grouped_histogram(frame, focus, {reference_name: valid & ~event, event_name: event})
            if bins:
                sections.append(histogram_section(
                    "driver-distribution",
                    f"{_measure_label(focus)} distribution by outcome",
                    bins,
                    series,
                    description="Row counts per value range for the strongest numeric association.",
                ))

    correlations = correlation_rows(frame, measures)
    if correlations:
        sections.append(table_section(
            "correlations",
            "Correlated measures",
            [
                {"key": "a", "label": "Measure A"},
                {"key": "b", "label": "Measure B"},
                {"key": "r", "label": "Pearson r", "format": "decimal", "align": "right"},
                {"key": "strength", "label": "Strength"},
            ],
            correlations,
            description="Strongest linear relationships between numeric measures.",
            note="Correlation is not causation, and a high correlation between two measures can make both redundant as predictors.",
        ))

    if not sections:
        sections.append(notice_section(
            "nothing-to-compare",
            "Not enough usable columns",
            "This dataset does not contain enough numeric or grouping columns for behaviour analysis.",
            tone="warning",
        ))

    limitations.extend([
        "Associations are measured on this file; they are not proof that a feature causes the outcome.",
        "Rates are unadjusted for other features, so overlapping effects are not separated.",
    ])
    if target and not target.get("confirmed"):
        limitations.append("The outcome column is a suggestion until confirmed; model-based scoring is not run here.")
    if target and target.get("polarity"):
        limitations.append(target["polarity"])
    if not caps.get("has_time"):
        limitations.append("No date column: repeat-purchase cadence, cohorts and weekday patterns cannot be computed for this dataset.")

    return module_payload(
        "behavior",
        caps,
        "ready",
        summary=summary,
        sections=sections,
        insights=insights,
        limitations=limitations,
    )


def segmentation_module(frame: pd.DataFrame, caps: dict) -> dict:
    target = caps.get("target")
    measures = usable_measures(caps, frame, limit=10)
    event, valid, event_name = event_mask(frame, target)

    outcome = None
    if target and target.get("kind") == "binary" and event.any():
        outcome = event.astype(int)

    result = cluster(frame, measures, target=(target or {}).get("column"), outcome=outcome, outcome_name=event_name)
    summary = [
        card("Rows clustered", result.get("rows_used", 0), "number"),
        card("Segments", result.get("k", 0), "number", hint="K-means, k chosen by silhouette"),
        card("Silhouette", result.get("silhouette"), "decimal", hint="-1 to 1; higher means better separated"),
    ]
    sections: list[dict] = []
    insights: list[dict] = []
    limitations: list[str] = []

    if not result.get("available"):
        reasons = result.get("notes", ["Clustering could not run on this dataset."])
        return module_payload(
            "segmentation",
            caps,
            "unavailable",
            summary=summary,
            sections=[notice_section("clustering-unavailable", "Clustering not available", " ".join(reasons), tone="warning")],
            requires=["At least 30 rows and 2 numeric features"],
            limitations=reasons,
        )

    clusters = result["clusters"]
    sections.append(bar_section(
        "segment-sizes",
        "Segment sizes",
        [
            {
                "label": f"Segment {row['cluster'] + 1}",
                "value": row["size"],
                "secondary": f"{row['share']}%" + (f" · {row['outcome_rate']}% {event_name.lower()}" if row.get("outcome_rate") is not None else ""),
            }
            for row in clusters
        ],
        description="Number of rows assigned to each segment.",
        kind="number",
    ))

    columns = [
        {"key": "segment", "label": "Segment"},
        {"key": "size", "label": "Rows", "format": "number", "align": "right"},
        {"key": "share", "label": "Share", "format": "percent", "align": "right"},
    ]
    if outcome is not None:
        columns.append({"key": "outcome_rate", "label": rate_label(event_name), "format": "percent", "align": "right"})
    columns.append({"key": "profile", "label": "Profile"})

    rows = []
    for row in clusters:
        rows.append({
            "segment": f"Segment {row['cluster'] + 1}",
            "size": row["size"],
            "share": row["share"],
            "outcome_rate": row.get("outcome_rate"),
            "profile": row.get("description") or "—",
        })
    sections.append(table_section(
        "segment-profiles",
        "Segment profiles",
        columns,
        rows,
        description="Mean feature values are compared with the dataset average; the profile lists the features that stand out.",
        note="Segments are descriptive groupings of rows, not predictions of which customers will leave.",
    ))

    if outcome is not None:
        rates = [row for row in clusters if row.get("outcome_rate") is not None]
        if rates:
            sections.append(bar_section(
                "segment-outcome",
                f"{rate_label(event_name)} by segment",
                [{"label": f"Segment {row['cluster'] + 1}", "value": row["outcome_rate"]} for row in rates],
                description="Observed outcome rate inside each cluster. Differences indicate where the outcome concentrates.",
                kind="percent",
            ))
            riskiest = max(rates, key=lambda row: row["outcome_rate"])
            insights.append({
                "title": f"Segment {riskiest['cluster'] + 1} has the highest observed {event_name.lower()} rate",
                "detail": (
                    f"{riskiest['outcome_rate']}% of its {riskiest['size']:,} rows are in the event class "
                    f"versus {target.get('event_share')}% overall."
                ),
                "tone": "warning",
            })

    silhouette = result.get("silhouette")
    if silhouette is not None:
        if silhouette < 0.25:
            limitations.append(
                f"Silhouette is {silhouette}, so the segments overlap substantially. Treat segment labels as a coarse summary."
            )
        else:
            limitations.append(f"Silhouette is {silhouette}; separation is moderate at best and depends on the chosen features.")
    limitations.extend([
        "K-means uses standardised numeric features; categorical columns are not part of the distance.",
        "Changing the feature list can change the segments — the definitions are shown above.",
    ])

    return module_payload(
        "segmentation",
        caps,
        "ready",
        summary=summary,
        sections=sections,
        insights=insights,
        limitations=limitations,
        method=result.get("method"),
    )
