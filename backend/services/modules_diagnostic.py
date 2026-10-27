"""
Diagnostic modules: Root Cause Analysis and Data Drift & BPR.

Root cause ranks statistically tested associations with the observed outcome and
reports effect sizes, p-values and a multiple-comparison correction. Drift
compares the active dataset with a genuine reference distribution — another
dataset or an earlier period — and refuses to invent drift scores when neither
exists.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

from services.semantics import humanize
from services.stats_lib import (
    bar_section,
    card,
    categorical_driver,
    chi_square_any,
    class_display,
    event_mask,
    kruskal_driver,
    module_payload,
    notice_section,
    num,
    numeric_driver,
    p_display,
    rate_label,
    table_section,
    usable_dimensions,
    usable_measures,
)

ALPHA = 0.05
PSI_WATCH = 0.1
PSI_SHIFTED = 0.25
MAX_DRIFT_FEATURES = 15


# ─── Root cause ─────────────────────────────────────────────────────────────

def rootcause_module(frame: pd.DataFrame, caps: dict) -> dict:
    target = caps.get("target")
    event, valid, event_name = event_mask(frame, target)
    reference_name = next(
        (class_display(target["column"], entry["label"]) for entry in (target or {}).get("classes", []) if str(entry["label"]) != str((target or {}).get("event"))),
        "Other",
    )
    measures = usable_measures(caps, frame)
    dimensions = usable_dimensions(caps, frame)

    sections: list[dict] = []
    insights: list[dict] = []
    limitations: list[str] = []

    if target and target.get("kind") in {"binary", "multiclass"} and int(valid.sum()) >= 30:
        drivers: list[dict] = []
        if target.get("kind") == "binary":
            for column in measures:
                driver = numeric_driver(frame, column, event, valid, event_name, reference_name)
                if driver:
                    drivers.append(driver)
            for column in dimensions:
                driver = categorical_driver(frame, column, event, valid, event_name)
                if driver:
                    drivers.append(driver)
        else:
            for column in measures:
                driver = kruskal_driver(frame, column, target["column"])
                if driver:
                    drivers.append(driver)
            for column in dimensions:
                driver = chi_square_any(frame, column, target["column"])
                if driver:
                    drivers.append(driver)

        if not drivers:
            return module_payload(
                "rootcause",
                caps,
                "unavailable",
                sections=[notice_section(
                    "no-drivers",
                    "No testable drivers",
                    "No numeric or grouping column had enough usable values to test against the outcome.",
                    tone="warning",
                )],
                requires=["Numeric or categorical feature columns with enough non-missing rows"],
                limitations=["Root cause analysis needs features that vary with the outcome."],
            )

        drivers.sort(key=lambda row: (abs(row["effect"] or 0)), reverse=True)
        threshold = ALPHA / max(1, len(drivers))
        for driver in drivers:
            p_value = driver.get("p_value")
            driver["significant"] = bool(p_value is not None and p_value <= threshold)
            driver["alpha"] = round(threshold, 6)

        summary = [
            card("Factors tested", len(drivers), "number"),
            card("Significant after correction", sum(1 for d in drivers if d["significant"]), "number", hint=f"Bonferroni α = {threshold:.2e}"),
            card("Rows analysed", int(valid.sum()), "number"),
            card(rate_label(event_name), target.get("event_share"), "percent"),
        ]

        sections.append(bar_section(
            "driver-strength",
            "Association strength by factor",
            [
                {
                    "label": driver["label"],
                    "value": abs(driver["effect"] or 0),
                    "secondary": f"p {p_display(driver['p_value'])}" + ("" if driver["significant"] else " · not significant"),
                }
                for driver in drivers[:12]
            ],
            description="Effect size: rank-biserial correlation for numeric factors, Cramér's V for groupings.",
            kind="decimal",
            note="Larger values mean the factor separates the outcome groups more strongly. This is association, not proof of causation.",
        ))

        rows = []
        for driver in drivers:
            rows.append({
                "factor": driver["label"],
                "type": "Numeric" if driver["type"] == "numeric" else "Grouping",
                "effect": driver["effect"],
                "effect_label": strength_label_safe(driver["effect"]),
                "p_value": p_display(driver["p_value"]),
                "significant": "Yes" if driver["significant"] else "No",
                "direction": driver.get("direction") or "—",
                "evidence": driver["evidence"],
            })
        sections.append(table_section(
            "driver-evidence",
            "Evidence table",
            [
                {"key": "factor", "label": "Factor"},
                {"key": "type", "label": "Type"},
                {"key": "effect", "label": "Effect size", "format": "decimal", "align": "right"},
                {"key": "effect_label", "label": "Magnitude"},
                {"key": "p_value", "label": "p-value", "align": "right"},
                {"key": "significant", "label": "Significant", "align": "center"},
                {"key": "direction", "label": "Direction"},
            ],
            rows,
            description=f"Each factor is tested against the observed outcome; the family-wise threshold is α = {threshold:.2e}.",
            note="p-values describe how unlikely the observed difference is under no association. A large effect with a wide confidence interval is still uncertain.",
        ))

        group_tables = []
        for driver in [d for d in drivers if d["type"] == "categorical"][:2]:
            for level in driver.get("levels", []):
                group_tables.append({
                    "factor": driver["label"],
                    "level": level["level"],
                    "n": level["n"],
                    "events": level["events"],
                    "rate": level["rate"],
                    "contribution": num((level["rate"] or 0) - (driver.get("baseline_rate") or 0), 2),
                })
        if group_tables:
            sections.append(table_section(
                "group-contribution",
                "Where the outcome concentrates",
                [
                    {"key": "factor", "label": "Factor"},
                    {"key": "level", "label": "Group"},
                    {"key": "n", "label": "Rows", "format": "number", "align": "right"},
                    {"key": "events", "label": event_name, "format": "number", "align": "right"},
                    {"key": "rate", "label": "Rate", "format": "percent", "align": "right"},
                    {"key": "contribution", "label": "vs baseline (pp)", "format": "decimal", "align": "right"},
                ],
                group_tables[:10],
                description="Observed outcome rate per group and its distance from the overall rate.",
            ))

        top = next((driver for driver in drivers if driver["significant"]), drivers[0])
        insights.append({
            "title": f"Leading measured factor: {top['label']}",
            "detail": f"{top['evidence']}. {strength_label_safe(top['effect']).title()} effect size.",
            "tone": "warning" if top["significant"] and abs(top["effect"] or 0) >= 0.1 else "info",
        })
        if len(drivers) > 1:
            second = drivers[1]
            insights.append({
                "title": f"Second factor: {second['label']}",
                "detail": second["evidence"],
                "tone": "info",
            })
        missing = _missing_columns(frame, limit=2)
        if missing:
            insights.append({
                "title": "Incomplete evidence",
                "detail": (
                    "These columns are missing enough rows to weaken the analysis: "
                    + ", ".join(f"{humanize(name)} ({share}%)" for name, share in missing)
                    + "."
                ),
                "tone": "warning",
            })

        limitations.extend([
            "This is an observational analysis of one file: it identifies associations, not proven causes.",
            f"Multiple comparisons were corrected with the Bonferroni threshold α = {threshold:.2e}; unmeasured confounders are not controlled for.",
            "Group rates are unadjusted; two correlated factors can describe the same underlying pattern.",
        ])
        if not target.get("confirmed"):
            limitations.append("The outcome column is a suggestion until confirmed; the same tests run either way, but modelling is disabled.")
        if target.get("polarity"):
            limitations.append(target["polarity"])

        return module_payload(
            "rootcause",
            caps,
            "ready",
            summary=summary,
            sections=sections,
            insights=insights,
            limitations=limitations,
            method="Mann-Whitney / chi-square (binary) or Kruskal-Wallis (multiclass) with Bonferroni correction",
        )

    if caps.get("has_time"):
        return _temporal_rootcause(frame, caps)

    return module_payload(
        "rootcause",
        caps,
        "unavailable",
        sections=[notice_section(
            "no-outcome-or-time",
            "Root cause analysis needs an outcome or a timeline",
            "This dataset has neither an outcome column to compare against nor a usable date column for a period comparison.",
            tone="warning",
        )],
        requires=["An outcome column (e.g. churn) or a date column with numeric measures"],
        limitations=["No evidence can be computed from this dataset in its current schema."],
    )


def strength_label_safe(effect: Optional[float]) -> str:
    magnitude = abs(effect or 0)
    if magnitude < 0.1:
        return "Negligible"
    if magnitude < 0.3:
        return "Small"
    if magnitude < 0.5:
        return "Moderate"
    return "Large"


def _missing_columns(frame: pd.DataFrame, limit: int = 3) -> list[tuple[str, float]]:
    rows = []
    for column in frame.columns:
        share = float(frame[column].isna().mean() * 100)
        if share >= 10:
            rows.append((column, round(share, 1)))
    rows.sort(key=lambda item: item[1], reverse=True)
    return rows[:limit]


def _temporal_rootcause(frame: pd.DataFrame, caps: dict) -> dict:
    """No outcome column: compare earlier and later periods of the measures."""
    coverage = caps["time_coverage"]
    time_column = coverage["column"]
    work = frame[[time_column] + usable_measures(caps, frame)].dropna(subset=[time_column]).sort_values(time_column)
    measures = usable_measures(caps, frame)
    if work.empty or not measures:
        return module_payload("rootcause", caps, "unavailable", limitations=["No usable dated measures."])

    midpoint = work[time_column].iloc[len(work) // 2]
    earlier = work[work[time_column] <= midpoint]
    later = work[work[time_column] > midpoint]
    rows = []
    for column in measures:
        before = earlier[column].dropna().astype(float)
        after = later[column].dropna().astype(float)
        if len(before) < 10 or len(after) < 10:
            continue
        statistic, p_value = stats.ks_2samp(before, after)
        shift = (after.mean() - before.mean()) / abs(before.mean()) * 100 if before.mean() else None
        rows.append({
            "factor": humanize(column),
            "earlier": num(before.mean(), 2),
            "later": num(after.mean(), 2),
            "shift_pct": num(shift, 2),
            "p_value": p_display(p_value),
            "effect": num(statistic, 3),
        })
    rows.sort(key=lambda row: row["effect"] or 0, reverse=True)

    sections = [
        notice_section(
            "no-outcome",
            "Change analysis instead of outcome drivers",
            "No churn/attrition-style outcome column exists, so this page measures what changed between the earlier and later halves of the timeline.",
        )
    ]
    if rows:
        sections.append(table_section(
            "period-change",
            "Measures by period",
            [
                {"key": "factor", "label": "Measure"},
                {"key": "earlier", "label": "Earlier mean", "format": "decimal", "align": "right"},
                {"key": "later", "label": "Later mean", "format": "decimal", "align": "right"},
                {"key": "shift_pct", "label": "Change", "format": "percent", "align": "right"},
                {"key": "effect", "label": "KS statistic", "format": "decimal", "align": "right"},
                {"key": "p_value", "label": "p-value", "align": "right"},
            ],
            rows,
            description=f"Split at the median date in '{time_column}'. The KS statistic is the largest gap between the two distributions.",
        ))
    return module_payload(
        "rootcause",
        caps,
        "ready",
        summary=[
            card("Measures compared", len(rows), "number"),
            card("Earlier rows", len(earlier), "number"),
            card("Later rows", len(later), "number"),
        ],
        sections=sections,
        limitations=["A period difference can be seasonality, a data-collection change or a real shift; it is not a causal explanation."],
        method="Kolmogorov-Smirnov two-sample comparison of earlier and later periods",
    )


# ─── Drift ──────────────────────────────────────────────────────────────────

def _psi(baseline: np.ndarray, current: np.ndarray, edges: np.ndarray) -> Optional[float]:
    base_counts, _ = np.histogram(baseline, bins=edges)
    curr_counts, _ = np.histogram(current, bins=edges)
    base_share = base_counts / max(1, base_counts.sum())
    curr_share = curr_counts / max(1, curr_counts.sum())
    epsilon = 1e-6
    base_share = np.clip(base_share, epsilon, None)
    curr_share = np.clip(curr_share, epsilon, None)
    value = float(np.sum((curr_share - base_share) * np.log(curr_share / base_share)))
    return round(min(value, 10.0), 4)


def _psi_categorical(baseline: pd.Series, current: pd.Series) -> Optional[float]:
    base = baseline.dropna().astype(str).value_counts(normalize=True)
    curr = current.dropna().astype(str).value_counts(normalize=True)
    if base.empty or curr.empty:
        return None
    levels = sorted(set(base.index) | set(curr.index))
    epsilon = 1e-6
    total = 0.0
    for level in levels:
        b = max(float(base.get(level, 0.0)), epsilon)
        c = max(float(curr.get(level, 0.0)), epsilon)
        total += (c - b) * np.log(c / b)
    return round(min(total, 10.0), 4)


def _status(psi: Optional[float]) -> str:
    if psi is None:
        return "unknown"
    if psi < PSI_WATCH:
        return "stable"
    if psi < PSI_SHIFTED:
        return "watch"
    return "shifted"


def compare_frames(baseline: pd.DataFrame, current: pd.DataFrame) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    skipped: list[str] = []
    shared = [column for column in baseline.columns if column in current.columns]
    for column in shared[:60]:
        before = baseline[column]
        after = current[column]
        before_non_null = before.dropna()
        after_non_null = after.dropna()
        if before_non_null.empty or after_non_null.empty:
            continue

        numeric_types = (pd.api.types.is_numeric_dtype(before), pd.api.types.is_numeric_dtype(after))
        if all(numeric_types) and before_non_null.nunique() > 10 and after_non_null.nunique() > 10:
            base_values = before_non_null.astype(float).to_numpy()
            curr_values = after_non_null.astype(float).to_numpy()
            edges = np.unique(np.quantile(base_values, np.linspace(0, 1, 11)))
            if len(edges) < 2:
                skipped.append(f"{humanize(column)} (constant)")
                continue
            edges[0] = -np.inf
            edges[-1] = np.inf
            psi = _psi(base_values, curr_values, edges)
            ks_stat, p_value = stats.ks_2samp(base_values, curr_values)
            rows.append({
                "feature": humanize(column),
                "column": column,
                "type": "numeric",
                "psi": psi,
                "status": _status(psi),
                "test": "KS",
                "statistic": num(ks_stat, 3),
                "p_value": p_display(p_value),
                "baseline": num(np.mean(base_values), 2),
                "current": num(np.mean(curr_values), 2),
                "change_pct": num(
                    (np.mean(curr_values) - np.mean(base_values)) / abs(np.mean(base_values)) * 100, 2
                ) if np.mean(base_values) else None,
                "baseline_n": int(len(base_values)),
                "current_n": int(len(curr_values)),
            })
        else:
            if before_non_null.nunique() > 50 or after_non_null.nunique() > 50:
                skipped.append(f"{humanize(column)} (high-cardinality text)")
                continue
            psi = _psi_categorical(before, after)
            if psi is None:
                continue
            table = pd.crosstab(before.astype(str), after.astype(str))
            p_value = None
            try:
                _, p_value, _, _ = stats.chi2_contingency(table)
            except ValueError:
                p_value = None
            top_before = before_non_null.astype(str).value_counts(normalize=True)
            top_after = after_non_null.astype(str).value_counts(normalize=True)
            rows.append({
                "feature": humanize(column),
                "column": column,
                "type": "categorical",
                "psi": psi,
                "status": _status(psi),
                "test": "chi-square",
                "statistic": None,
                "p_value": p_display(p_value),
                "baseline": str(top_before.index[0]),
                "current": str(top_after.index[0]),
                "change_pct": num((float(top_after.iloc[0]) - float(top_before.iloc[0])) * 100, 2),
                "baseline_n": int(len(before_non_null)),
                "current_n": int(len(after_non_null)),
            })

    rows.sort(key=lambda row: row["psi"] or 0, reverse=True)
    return rows[:MAX_DRIFT_FEATURES], skipped


def drift_module(
    frame: pd.DataFrame,
    caps: dict,
    reference_frame: Optional[pd.DataFrame] = None,
    reference_label: Optional[str] = None,
) -> dict:
    module_status = caps["modules"]["drift"]
    if reference_frame is None and (module_status["status"] == "partial" or not caps.get("has_time")):
        candidates = module_status.get("reference_candidates", [])
        sections = [
            notice_section(
                "needs-reference",
                "A baseline is required to measure drift",
                "Drift compares two distributions. This dataset has no date column, so the only valid baseline is another dataset "
                "from the same source. No drift score is estimated or simulated without one.",
                tone="warning",
            )
        ]
        if candidates:
            sections.append(notice_section(
                "available-references",
                "Datasets available as a reference",
                "Choose one of: " + ", ".join(f"{row['name']} ({row['rows']:,} rows)" for row in candidates) + ".",
                tone="info",
            ))
        return module_payload(
            "drift",
            caps,
            "partial",
            summary=[
                card("Features compared", 0, "number"),
                card("Reference datasets", len(candidates), "number"),
            ],
            sections=sections,
            requires=module_status.get("reasons", []) + module_status.get("requires", []),
            limitations=[
                "Without a reference distribution there is no honest drift measurement for this dataset.",
                "Business process rules (BPR) are not evaluated here: they require process-level data that this file does not contain.",
            ],
            reference_candidates=candidates,
            reference=None,
        )

    if reference_frame is not None:
        baseline = reference_frame
        current = frame
        baseline_label = reference_label or "reference dataset"
        mode = "reference"
        description = f"Baseline: {baseline_label} ({len(baseline):,} rows). Current: {caps['dataset']['name']} ({len(current):,} rows)."
    else:
        time_column = caps["time_coverage"]["column"]
        work = frame.dropna(subset=[time_column]).sort_values(time_column)
        split = max(1, int(len(work) * 0.6))
        baseline = work.iloc[:split]
        current = work.iloc[split:]
        baseline_label = f"earlier {len(baseline):,} rows"
        mode = "time"
        description = (
            f"Baseline: earliest {len(baseline):,} rows of '{time_column}'. "
            f"Current: latest {len(current):,} rows."
        )

    rows, skipped = compare_frames(baseline, current)
    if not rows:
        return module_payload(
            "drift",
            caps,
            "partial",
            sections=[notice_section(
                "no-comparable-features",
                "No comparable features",
                "The two distributions do not share usable numeric or categorical columns, so no drift can be measured.",
                tone="warning",
            )],
            requires=["Two datasets with overlapping feature columns"],
            limitations=[f"Skipped columns: {', '.join(skipped[:5])}."] if skipped else [],
            reference={"label": baseline_label, "mode": mode},
        )

    shifted = [row for row in rows if row["status"] == "shifted"]
    watch = [row for row in rows if row["status"] == "watch"]
    stable = [row for row in rows if row["status"] == "stable"]
    summary = [
        card("Features compared", len(rows), "number"),
        card("Shifted", len(shifted), "number", hint=f"PSI ≥ {PSI_SHIFTED}"),
        card("Watch", len(watch), "number", hint=f"PSI {PSI_WATCH}–{PSI_SHIFTED}"),
        card("Stable", len(stable), "number", hint=f"PSI < {PSI_WATCH}"),
    ]

    sections = [
        bar_section(
            "psi",
            "Population stability index by feature",
            [
                {"label": row["feature"], "value": row["psi"], "secondary": row["status"]}
                for row in rows[:12]
            ],
            description=description,
            kind="decimal",
            note=f"PSI below {PSI_WATCH} is stable, {PSI_WATCH}–{PSI_SHIFTED} warrants watching, at or above {PSI_SHIFTED} is a material shift.",
        ),
        table_section(
            "drift-detail",
            "Feature-level comparison",
            [
                {"key": "feature", "label": "Feature"},
                {"key": "type", "label": "Type"},
                {"key": "baseline", "label": "Baseline", "align": "right"},
                {"key": "current", "label": "Current", "align": "right"},
                {"key": "change_pct", "label": "Change", "format": "percent", "align": "right"},
                {"key": "psi", "label": "PSI", "format": "decimal", "align": "right"},
                {"key": "status", "label": "Status"},
                {"key": "test", "label": "Test"},
                {"key": "p_value", "label": "p-value", "align": "right"},
            ],
            rows,
            description="Numeric rows show means; categorical rows show the most common level.",
            note="PSI uses deciles of the baseline distribution. A p-value is shown for the distribution test but PSI drives the status.",
        ),
    ]

    insights = []
    if shifted:
        top = shifted[0]
        insights.append({
            "title": f"{top['feature']} has shifted",
            "detail": f"PSI {top['psi']} ({top['status']}) between {baseline_label} and the current rows.",
            "tone": "warning",
        })
    if not shifted:
        insights.append({
            "title": "No feature crossed the shift threshold",
            "detail": f"All {len(rows)} compared features are stable or on watch. That is not proof the process is unchanged, only that these distributions are similar.",
            "tone": "info",
        })
    if skipped:
        insights.append({
            "title": "Some columns were skipped",
            "detail": ", ".join(skipped[:4]) + ". They could not be compared reliably.",
            "tone": "info",
        })

    return module_payload(
        "drift",
        caps,
        "ready",
        summary=summary,
        sections=sections,
        insights=insights,
        limitations=[
            "PSI depends on the binning scheme; different baselines can produce different scores.",
            "A distribution shift is not a business process defect on its own — it needs domain interpretation.",
            "Business process rules (BPR) are not scored: this dataset contains no process execution records.",
        ],
        reference={"label": baseline_label, "mode": mode, "rows": len(baseline)},
        reference_candidates=caps["modules"]["drift"].get("reference_candidates", []),
        method=f"PSI on baseline deciles with KS / chi-square tests ({mode} baseline)",
    )
