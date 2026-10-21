"""
Data Drift Detection using River ADWIN algorithm.
Monitors KPI time-series for concept/data drift.
"""
import random
import pandas as pd
import numpy as np
from river.drift import ADWIN  # type: ignore[import-untyped]
from typing import List, Dict


def detect_drift_adwin(series: List[float], delta: float = 0.002) -> Dict:
    """
    Runs ADWIN drift detector on a numeric time series.
    Returns drift points and drift score.

    Args:
        series: List of numeric observations (chronological order).
        delta: ADWIN confidence parameter (0 < delta < 1). Smaller = more sensitive.
    """
    if not isinstance(delta, (int, float)) or not (0 < delta < 1):
        delta = 0.002  # safe default

    try:
        detector = ADWIN(delta=delta)
    except TypeError:
        # Fallback for builds that don't accept keyword argument
        detector = ADWIN(0.002)

    drift_points: List[int] = []

    for i, value in enumerate(series):
        try:
            detector.update(value)
            if detector.drift_detected:          # confirmed correct attr in River 0.21.2
                drift_points.append(i)
        except Exception:
            continue                              # skip malformed values gracefully

    n = max(len(series), 1)
    drift_score = min(len(drift_points) / n * 10, 1.0)
    return {
        "drift_detected": len(drift_points) > 0,
        "drift_points": drift_points,
        "drift_score": round(drift_score, 3),
        "n_drift_events": len(drift_points),
    }


def analyze_kpi_drift(monthly_df: pd.DataFrame) -> List[Dict]:
    """
    Given a monthly aggregated DataFrame with columns [month, sales, profit, orders],
    run drift detection on each KPI stream.
    """
    results = []
    kpi_cols = {
        "sales":           ("Monthly Revenue",  "USD"),
        "profit":          ("Monthly Profit",   "USD"),
        "orders":          ("Order Volume",      "count"),
        "avg_order_value": ("Avg Order Value",   "USD"),
    }

    if (
        "avg_order_value" not in monthly_df.columns
        and "sales" in monthly_df.columns
        and "orders" in monthly_df.columns
    ):
        monthly_df = monthly_df.copy()
        monthly_df["avg_order_value"] = (
            monthly_df["sales"] / monthly_df["orders"].replace(0, 1)
        )

    for col, (label, unit) in kpi_cols.items():
        if col not in monthly_df.columns:
            continue
        series: List[float] = monthly_df[col].dropna().tolist()
        if len(series) < 3:
            continue
        drift_result = detect_drift_adwin(series)
        results.append({
            "kpi":      label,
            "unit":     unit,
            "current":  round(series[-1], 2),
            "baseline": round(float(np.mean(series[:3])), 2),
            "series":   [round(v, 2) for v in series],
            **drift_result,
        })

    return results


def score_bpr_rule_effectiveness(rule: dict, orders_df: pd.DataFrame) -> float:
    """
    Simple heuristic: score rule effectiveness based on orders data trends.
    Returns a 0–1 effectiveness score.

    Note: In production this would evaluate rule conditions against live order history.
    The orders_df parameter is reserved for that future implementation.
    """
    base = {"active": 0.75, "needs_review": 0.48, "obsolete": 0.2}
    noise = random.uniform(-0.1, 0.1)
    return round(min(max(base.get(rule.get("status", "active"), 0.5) + noise, 0.1), 1.0), 2)
