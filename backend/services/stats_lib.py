"""
Shared statistics and presentation helpers for the dataset-adaptive modules.

Every number returned by these helpers is computed from the committed frame.
Helpers return plain Python types so the payloads are JSON-safe.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd
from scipy import stats

from services.semantics import humanize

MAX_FEATURES = 12


# ─── Formatting ──────────────────────────────────────────────────────────────

def num(value: Any, digits: int = 2) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return round(number, digits)


def count(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def fmt(value: Any, kind: str = "number") -> str:
    if value is None:
        return "—"
    if kind == "text":
        return str(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not np.isfinite(number):
        return "—"
    if kind == "percent":
        return f"{number:,.1f}%"
    if kind == "currency":
        return f"${number:,.0f}" if abs(number) >= 1000 else f"${number:,.2f}"
    if kind == "decimal":
        return f"{number:,.2f}"
    if kind == "rate":
        return f"{number * 100:,.1f}%"
    return f"{number:,.0f}"


def card(label: str, value: Any, kind: str = "number", hint: Optional[str] = None, display: Optional[str] = None) -> dict:
    return {
        "label": label,
        "value": num(value, 4) if kind != "text" else None,
        "display": display if display is not None else fmt(value, kind),
        "format": kind,
        "hint": hint,
    }


def bar_section(
    section_id: str,
    title: str,
    data: list[dict],
    description: Optional[str] = None,
    kind: str = "number",
    horizontal: bool = True,
    note: Optional[str] = None,
) -> dict:
    return {
        "id": section_id,
        "kind": "bar",
        "title": title,
        "description": description,
        "format": kind,
        "horizontal": horizontal,
        "note": note,
        "data": [
            {"label": str(row["label"]), "value": num(row.get("value"), 4), "secondary": row.get("secondary")}
            for row in data
        ],
    }


def table_section(
    section_id: str,
    title: str,
    columns: list[dict],
    rows: list[dict],
    description: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    return {
        "id": section_id,
        "kind": "table",
        "title": title,
        "description": description,
        "columns": columns,
        "rows": rows,
        "note": note,
    }


def notice_section(section_id: str, title: str, body: str, tone: str = "info") -> dict:
    return {"id": section_id, "kind": "notice", "title": title, "body": body, "tone": tone}


def histogram_section(
    section_id: str,
    title: str,
    bins: list[dict],
    series: list[str],
    description: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    return {
        "id": section_id,
        "kind": "histogram",
        "title": title,
        "description": description,
        "series": series,
        "data": bins,
        "note": note,
    }


def line_section(
    section_id: str,
    title: str,
    data: list[dict],
    series: list[str],
    description: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    return {
        "id": section_id,
        "kind": "line",
        "title": title,
        "description": description,
        "series": series,
        "data": data,
        "note": note,
    }


def payoff_section(section_id: str, title: str, labels: list[str], matrix: list[list[int]], description: Optional[str] = None) -> dict:
    return {
        "id": section_id,
        "kind": "confusion",
        "title": title,
        "description": description,
        "labels": labels,
        "matrix": matrix,
    }


def module_payload(
    module: str,
    capabilities: dict,
    status: str,
    summary: Optional[list[dict]] = None,
    sections: Optional[list[dict]] = None,
    insights: Optional[list[dict]] = None,
    limitations: Optional[list[str]] = None,
    requires: Optional[list[str]] = None,
    **extra: Any,
) -> dict:
    return {
        "has_data": True,
        "compatible": status != "unavailable",
        "mode": "adaptive",
        "module": module,
        "status": status,
        "dataset": capabilities.get("dataset"),
        "schema_label": capabilities.get("schema_label"),
        "target": capabilities.get("target"),
        "summary": summary or [],
        "sections": sections or [],
        "insights": insights or [],
        "limitations": limitations or [],
        "requires": requires or [],
        **extra,
    }


# ─── Column roles / target helpers ───────────────────────────────────────────

def _target_column(capabilities: dict) -> Optional[str]:
    return (capabilities.get("target") or {}).get("column")


def usable_measures(capabilities: dict, frame: pd.DataFrame, limit: int = MAX_FEATURES) -> list[str]:
    """Numeric predictors, never the outcome column itself."""
    target = _target_column(capabilities)
    available = [
        column for column in capabilities["roles"]["measures"]
        if column in frame.columns and column != target
    ]
    return available[:limit]


def usable_dimensions(capabilities: dict, frame: pd.DataFrame, limit: int = 8) -> list[str]:
    """Grouping columns, never the outcome column itself."""
    target = _target_column(capabilities)
    columns = capabilities["roles"]["binary"] + capabilities["roles"]["categorical"]
    return [column for column in columns if column in frame.columns and column != target][:limit]


def rate_label(event_name: str) -> str:
    return "Churn rate" if event_name == "Churned" else f"{event_name} rate"


def class_display(column: str, label: str) -> str:
    low = str(label).strip().lower()
    base = str(column).lower()
    churn_like = any(word in base for word in ("churn", "attrition", "exit", "cancel", "left", "defect", "unsubscrib"))
    if churn_like:
        if low in {"1", "true", "yes", "churned", "churn", "left", "exited", "cancelled", "canceled", "attrition"}:
            return "Churned"
        if low in {"0", "false", "no", "active", "retained", "stayed", "current"}:
            return "Retained"
    if low in {"1", "true", "t", "yes", "y"}:
        return "Yes"
    if low in {"0", "false", "f", "no", "n"}:
        return "No"
    return str(label)


def event_mask(frame: pd.DataFrame, target: Optional[dict]) -> tuple[pd.Series, pd.Series, str]:
    """Boolean mask of the event class, mask of usable rows, and the event name."""
    if not target or target.get("column") not in frame.columns:
        empty = pd.Series(False, index=frame.index)
        return empty, empty, "event"
    series = frame[target["column"]].astype("string").str.strip()
    valid = series.notna()
    label = target.get("event") or (target["classes"][ -1 ]["label"] if target.get("classes") else None)
    if target.get("kind") != "binary" or label is None:
        empty = pd.Series(False, index=frame.index)
        return empty, valid, class_display(target["column"], str(label or ""))
    mask = series == str(label)
    return mask, valid, class_display(target["column"], str(label))


def class_labels(frame: pd.DataFrame, target: dict) -> list[str]:
    values = frame[target["column"]].dropna().astype(str).str.strip()
    return [str(value) for value in sorted(values.unique().tolist())]


# ─── Distributions ───────────────────────────────────────────────────────────

def format_bound(value: float, digits: int = 2) -> str:
    number = float(value)
    if abs(number) < 5 * 10 ** (-(digits + 1)):
        number = 0.0
    return f"{number:,.{digits}f}"


def histogram(values: pd.Series, bins: int = 10) -> list[dict]:
    series = values.dropna().astype(float)
    if series.empty:
        return []
    edges_count = int(min(max(3, bins), max(3, series.nunique())))
    counts, edges = np.histogram(series.to_numpy(), bins=edges_count)
    return [
        {"bin": f"{format_bound(edges[index])} – {format_bound(edges[index + 1])}", "count": int(counts[index])}
        for index in range(len(counts))
    ]


def grouped_histogram(
    frame: pd.DataFrame,
    column: str,
    groups: dict[str, pd.Series],
    bins: int = 8,
) -> tuple[list[dict], list[str]]:
    series = frame[column].dropna().astype(float)
    if series.empty:
        return [], []
    low, high = float(series.min()), float(series.max())
    if high <= low:
        high = low + 1
    edges = np.linspace(low, high, min(bins, 10) + 1)
    names = list(groups.keys())
    rows: list[dict] = []
    for index in range(len(edges) - 1):
        lower, upper = edges[index], edges[index + 1]
        row: dict = {"bin": f"{format_bound(lower)} – {format_bound(upper)}"}
        for name, mask in groups.items():
            values = frame.loc[mask, column].dropna().astype(float)
            if index == len(edges) - 2:
                row[name] = int(((values >= lower) & (values <= upper)).sum())
            else:
                row[name] = int(((values >= lower) & (values < upper)).sum())
        rows.append(row)
    return rows, names


# ─── Associations ────────────────────────────────────────────────────────────

def strength_label(effect: float) -> str:
    magnitude = abs(effect)
    if magnitude < 0.1:
        return "negligible"
    if magnitude < 0.3:
        return "small"
    if magnitude < 0.5:
        return "moderate"
    return "large"


def p_display(p: Optional[float]) -> str:
    if p is None:
        return "—"
    if p < 0.001:
        return "< 0.001"
    return f"{p:.3f}"


def numeric_driver(
    frame: pd.DataFrame,
    column: str,
    mask: pd.Series,
    valid: pd.Series,
    event_name: str,
    reference_name: str,
) -> Optional[dict]:
    """Mann-Whitney comparison of a measure between the two outcome groups."""
    if not mask.any() or not (valid & ~mask).any():
        return None
    group = frame.loc[mask, column].dropna().astype(float)
    reference = frame.loc[valid & ~mask, column].dropna().astype(float)
    if len(group) < 10 or len(reference) < 10:
        return None
    try:
        statistic, p_value = stats.mannwhitneyu(group, reference, alternative="two-sided")
    except ValueError:
        return None
    effect = 1 - (2 * float(statistic)) / (len(group) * len(reference))
    return {
        "factor": column,
        "label": humanize(column),
        "type": "numeric",
        "effect": num(effect, 4),
        "effect_label": strength_label(effect),
        "p_value": num(p_value, 6),
        "statistic": num(statistic, 2),
        "group_mean": num(group.mean(), 2),
        "group_median": num(group.median(), 2),
        "reference_mean": num(reference.mean(), 2),
        "reference_median": num(reference.median(), 2),
        "group_n": int(len(group)),
        "reference_n": int(len(reference)),
        "direction": "higher" if group.median() > reference.median() else "lower",
        "event_name": event_name,
        "reference_name": reference_name,
        "evidence": (
            f"median {group.median():,.2f} vs {reference.median():,.2f} "
            f"({event_name} vs {reference_name}); Mann-Whitney p = {p_display(p_value)}"
        ),
    }


def categorical_driver(
    frame: pd.DataFrame,
    column: str,
    mask: pd.Series,
    valid: pd.Series,
    event_name: str,
) -> Optional[dict]:
    """Chi-square association between a grouping column and the outcome."""
    work = frame.loc[valid, [column]].copy()
    work["_event"] = mask.loc[valid].astype(int)
    work = work.dropna(subset=[column])
    if work.empty:
        return None
    table = pd.crosstab(work[column].astype(str), work["_event"])
    if table.shape[0] < 2 or table.shape[1] < 2:
        return None
    try:
        chi2, p_value, _, _ = stats.chi2_contingency(table)
    except ValueError:
        return None
    total = int(table.to_numpy().sum())
    denominator = total * (min(table.shape) - 1)
    cramers_v = float(np.sqrt(chi2 / denominator)) if denominator else 0.0

    levels = []
    for level, row in table.iterrows():
        observations = int(row.sum())
        events = int(row.get(1, 0))
        levels.append({
            "level": str(level),
            "n": observations,
            "events": events,
            "rate": num(events / observations * 100, 2) if observations else None,
        })
    levels.sort(key=lambda item: (item["rate"] or 0), reverse=True)
    worst = levels[0] if levels else None
    baseline = num(table.get(1, pd.Series(dtype=int)).sum() / total * 100, 2) if total else None
    return {
        "factor": column,
        "label": humanize(column),
        "type": "categorical",
        "effect": num(cramers_v, 4),
        "effect_label": strength_label(cramers_v),
        "p_value": num(p_value, 6),
        "statistic": num(chi2, 2),
        "levels": levels,
        "baseline_rate": baseline,
        "worst_level": worst,
        "direction": f"highest {event_name.lower()} rate in {worst['level']}" if worst else None,
        "evidence": (
            f"chi-square p = {p_display(p_value)}; Cramér's V = {cramers_v:.3f}"
            + (f"; highest rate {worst['rate']:.1f}% in '{worst['level']}'" if worst and worst["rate"] is not None else "")
        ),
    }


def kruskal_driver(
    frame: pd.DataFrame,
    column: str,
    target_column: str,
) -> Optional[dict]:
    """Kruskal-Wallis comparison of a measure across 3+ outcome classes."""
    work = frame[[column, target_column]].dropna()
    groups = [group[column].astype(float).to_numpy() for _, group in work.groupby(work[target_column].astype(str)) if len(group) >= 10]
    if len(groups) < 3:
        return None
    try:
        statistic, p_value = stats.kruskal(*groups)
    except ValueError:
        return None
    n = sum(len(group) for group in groups)
    effect = max(0.0, (float(statistic) - len(groups) + 1) / max(1, n - len(groups)))
    return {
        "factor": column,
        "label": humanize(column),
        "type": "numeric",
        "effect": num(effect, 4),
        "effect_label": strength_label(effect),
        "p_value": num(p_value, 6),
        "statistic": num(statistic, 2),
        "direction": f"differs across {len(groups)} classes",
        "evidence": f"Kruskal-Wallis p = {p_display(p_value)}; epsilon² = {effect:.3f}",
    }


def chi_square_any(frame: pd.DataFrame, column: str, target_column: str) -> Optional[dict]:
    work = frame[[column, target_column]].dropna()
    if work.empty:
        return None
    table = pd.crosstab(work[column].astype(str), work[target_column].astype(str))
    if min(table.shape) < 2:
        return None
    try:
        chi2, p_value, _, _ = stats.chi2_contingency(table)
    except ValueError:
        return None
    total = int(table.to_numpy().sum())
    denominator = total * (min(table.shape) - 1)
    cramers_v = float(np.sqrt(chi2 / denominator)) if denominator else 0.0
    return {
        "factor": column,
        "label": humanize(column),
        "type": "categorical",
        "effect": num(cramers_v, 4),
        "effect_label": strength_label(cramers_v),
        "p_value": num(p_value, 6),
        "statistic": num(chi2, 2),
        "direction": f"association across {table.shape[0]} × {table.shape[1]} levels",
        "evidence": f"chi-square p = {p_display(p_value)}; Cramér's V = {cramers_v:.3f}",
    }


def band_table(
    frame: pd.DataFrame,
    column: str,
    mask: pd.Series,
    valid: pd.Series,
    event_name: str,
    bins: int = 5,
) -> list[dict]:
    """Outcome rate per quantile band of a measure."""
    series = frame[column].astype(float)
    usable = valid & series.notna()
    if usable.sum() < 40:
        return []
    try:
        bands = pd.qcut(series[usable], q=bins, duplicates="drop")
    except (ValueError, TypeError):
        return []
    work = pd.DataFrame({
        "band": bands,
        "event": mask[usable].astype(int),
        "value": series[usable],
    })
    rows = []
    for interval, group in work.groupby("band", observed=True):
        observations = int(len(group))
        events = int(group["event"].sum())
        rows.append({
            "factor": humanize(column),
            "band": f"{format_bound(float(interval.left))} – {format_bound(float(interval.right))}",
            "n": observations,
            "events": events,
            "rate": num(events / observations * 100, 2) if observations else None,
            "mean": num(group["value"].mean(), 2),
            "event_name": event_name,
        })
    return rows


def correlation_rows(frame: pd.DataFrame, measures: list[str], limit: int = 8) -> list[dict]:
    columns = [column for column in measures if column in frame.columns]
    if len(columns) < 2:
        return []
    matrix = frame[columns].apply(pd.to_numeric, errors="coerce").corr()
    rows = []
    for index, left in enumerate(columns):
        for right in columns[index + 1:]:
            value = matrix.loc[left, right]
            if pd.isna(value):
                continue
            rows.append({
                "a": humanize(left),
                "b": humanize(right),
                "r": num(value, 3),
                "strength": strength_label(float(value)),
                "direction": "positive" if value > 0 else "negative",
            })
    rows.sort(key=lambda row: abs(row["r"] or 0), reverse=True)
    return rows[:limit]


def top_dimension_signal(
    frame: pd.DataFrame,
    dimensions: list[str],
    mask: pd.Series,
    valid: pd.Series,
    event_name: str,
) -> list[dict]:
    drivers = []
    for column in dimensions:
        driver = categorical_driver(frame, column, mask, valid, event_name)
        if driver:
            drivers.append(driver)
    drivers.sort(key=lambda row: abs(row["effect"] or 0), reverse=True)
    return drivers
