"""
Data drift detection and BPR rule evaluation.

Two independent signals are produced for every monthly KPI:

* **ADWIN** (River) streams the series and reports exact change points.
* **PSI** (population stability index) compares the earlier part of the history
  with the most recent window, which catches gradual mix shifts that a
  change-point detector alone can miss.

BPR rules are evaluated against monthly metric series computed from the orders
table — trigger history, trigger rate, last triggered month and a measured
effectiveness score. Nothing here is random.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from river.drift import ADWIN  # type: ignore[import-untyped]

# ─────────────────────────────────────────────────────────────────────────────
# ADWIN
# ─────────────────────────────────────────────────────────────────────────────
def detect_drift_adwin(series: List[float], delta: float = 0.002) -> Dict:
    """
    Run ADWIN over a numeric series (chronological order).

    Returns the change-point indices plus the mean shift they imply.
    """
    if not isinstance(delta, (int, float)) or not (0 < delta < 1):
        delta = 0.002

    values = [float(value) for value in series if value is not None and not pd.isna(value)]
    if len(values) < 3:
        return {
            "drift_detected": False,
            "drift_points": [],
            "drift_score": 0.0,
            "n_drift_events": 0,
            "mean_before": round(float(np.mean(values)), 2) if values else 0.0,
            "mean_after": round(float(np.mean(values)), 2) if values else 0.0,
            "magnitude_pct": 0.0,
        }

    try:
        detector = ADWIN(delta=delta)
    except TypeError:  # pragma: no cover - older River builds
        detector = ADWIN(0.002)

    drift_points: List[int] = []
    for index, value in enumerate(values):
        try:
            detector.update(value)
            if detector.drift_detected:
                drift_points.append(index)
        except Exception:
            continue

    # Drift score: share of the series flagged as change points, amplified so a
    # single break in a four-year history still reads as more than noise.
    drift_score = min(len(drift_points) / max(len(values), 1) * 12, 1.0)

    if drift_points:
        last_break = drift_points[-1]
        before = values[max(0, last_break - 6):last_break]
        after = values[last_break:]
        mean_before = float(np.mean(before)) if before else float(np.mean(values))
        mean_after = float(np.mean(after)) if after else float(np.mean(values))
    else:
        mean_before = float(np.mean(values))
        mean_after = float(np.mean(values[-3:]))

    magnitude_pct = round((mean_after - mean_before) / abs(mean_before) * 100, 1) if mean_before else 0.0

    return {
        "drift_detected": len(drift_points) > 0,
        "drift_points": drift_points,
        "drift_score": round(drift_score, 3),
        "n_drift_events": len(drift_points),
        "mean_before": round(mean_before, 2),
        "mean_after": round(mean_after, 2),
        "magnitude_pct": magnitude_pct,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PSI
# ─────────────────────────────────────────────────────────────────────────────
def _safe_psi(expected: np.ndarray, actual: np.ndarray) -> float:
    epsilon = 1e-4
    expected = np.clip(expected, epsilon, None)
    actual = np.clip(actual, epsilon, None)
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def psi_label(psi: Optional[float]) -> str:
    if psi is None:
        return "unknown"
    if psi < 0.1:
        return "stable"
    if psi < 0.25:
        return "moderate"
    return "significant"


def psi_numeric(expected: List[float], actual: List[float], bins: int = 8) -> tuple[Optional[float], List[Dict]]:
    """PSI over quantile bins of the baseline window."""
    exp = np.asarray([v for v in expected if v is not None and not pd.isna(v)], dtype=float)
    act = np.asarray([v for v in actual if v is not None and not pd.isna(v)], dtype=float)
    if len(exp) < 5 or len(act) < 2:
        return None, []

    # Quantile edges are taken from the combined windows: with only a handful of
    # monthly observations per window, baseline-only edges would put every recent
    # high value in the top bin and manufacture a huge PSI.
    combined = np.concatenate([exp, act])
    edges = np.unique(np.quantile(combined, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return None, []
    edges[0], edges[-1] = -np.inf, np.inf

    exp_counts, _ = np.histogram(exp, bins=edges)
    act_counts, _ = np.histogram(act, bins=edges)
    exp_share = exp_counts / max(exp_counts.sum(), 1)
    act_share = act_counts / max(act_counts.sum(), 1)

    distribution = []
    for i in range(len(edges) - 1):
        low, high = edges[i], edges[i + 1]
        label = (
            f"< {high:,.0f}" if not np.isfinite(low)
            else f"≥ {low:,.0f}" if not np.isfinite(high)
            else f"{low:,.0f} – {high:,.0f}"
        )
        distribution.append(
            {"band": label, "baseline": round(float(exp_share[i]) * 100, 1), "recent": round(float(act_share[i]) * 100, 1)}
        )

    return round(_safe_psi(exp_share, act_share), 3), distribution


def psi_categorical(expected: List[str], actual: List[str], top: int = 6) -> tuple[Optional[float], List[Dict]]:
    exp = pd.Series([v if v is not None else "Unknown" for v in expected])
    act = pd.Series([v if v is not None else "Unknown" for v in actual])
    if exp.empty or act.empty:
        return None, []

    exp_share = exp.value_counts(normalize=True)
    act_share = act.value_counts(normalize=True)
    labels = exp_share.index.union(act_share.index)

    psi = _safe_psi(
        exp_share.reindex(labels, fill_value=0).to_numpy(),
        act_share.reindex(labels, fill_value=0).to_numpy(),
    )

    ranked = sorted(
        labels,
        key=lambda label: abs(act_share.get(label, 0) - exp_share.get(label, 0)),
        reverse=True,
    )[:top]
    distribution = [
        {
            "band": str(label),
            "baseline": round(float(exp_share.get(label, 0)) * 100, 1),
            "recent": round(float(act_share.get(label, 0)) * 100, 1),
        }
        for label in ranked
    ]
    return round(psi, 3), distribution


# ─────────────────────────────────────────────────────────────────────────────
# KPI drift
# ─────────────────────────────────────────────────────────────────────────────
KPI_COLUMNS = {
    "sales": ("Monthly Revenue", "USD", "currency"),
    "profit": ("Monthly Profit", "USD", "currency"),
    "orders": ("Order Volume", "count", "number"),
    "avg_order_value": ("Avg Order Value", "USD", "currency"),
    "margin": ("Profit Margin", "%", "percent"),
}


def analyze_kpi_drift(monthly_df: pd.DataFrame) -> List[Dict]:
    """ADWIN + PSI for every KPI stream in a monthly aggregated frame."""
    if monthly_df.empty:
        return []

    work = monthly_df.copy().reset_index(drop=True)

    if "month" in work.columns:
        labels = work["month"].astype(str).tolist()
    elif "ds" in work.columns:
        labels = pd.to_datetime(work["ds"]).dt.strftime("%Y-%m").tolist()
    else:
        labels = [f"M{i + 1}" for i in range(len(work))]

    if "avg_order_value" not in work.columns and {"sales", "orders"}.issubset(work.columns):
        work["avg_order_value"] = work["sales"] / work["orders"].replace(0, 1)
    if "margin" not in work.columns and {"sales", "profit"}.issubset(work.columns):
        work["margin"] = np.where(work["sales"] != 0, work["profit"] / work["sales"] * 100, 0.0)

    results: List[Dict] = []
    for column, (label, unit, fmt) in KPI_COLUMNS.items():
        if column not in work.columns:
            continue
        series = pd.to_numeric(work[column], errors="coerce").dropna()
        if len(series) < 4:
            continue

        values = series.tolist()
        index_labels = [labels[i] for i in series.index if i < len(labels)]
        adwin = detect_drift_adwin(values)

        split = max(3, len(values) // 2)
        baseline_window = values[:split]
        recent_window = values[-split:]

        # PSI is not used on raw KPI levels: a growing business shifts the whole
        # distribution and PSI would flag every stream. Level shift, volatility
        # change and ADWIN change points answer the "did this KPI move?" question
        # directly. PSI is applied to feature mixes further below, where it belongs.
        psi = None
        distribution: List[Dict] = []

        n = len(values)
        recent_mean = float(np.mean(values[-3:]))
        prior_mean = float(np.mean(values[-6:-3])) if n >= 6 else float(np.mean(values[:-3] or values))
        recent_delta = round((recent_mean - prior_mean) / abs(prior_mean) * 100, 1) if prior_mean else None

        # Level shift: last six months versus the six before (or thirds for short series).
        level_window = min(6, max(2, n // 3))
        level_recent = float(np.mean(values[-level_window:]))
        level_prior = float(np.mean(values[-level_window * 2:-level_window])) if n >= level_window * 2 else float(np.mean(values[:-level_window]))
        level_pct = round((level_recent - level_prior) / abs(level_prior) * 100, 1) if level_prior else None

        vol_recent = float(np.std(values[-level_window:])) / abs(level_recent) * 100 if level_recent else 0.0
        vol_prior = float(np.std(values[-level_window * 2:-level_window])) / abs(level_prior) * 100 if level_prior and n >= level_window * 2 else vol_recent
        volatility_change = round(vol_recent - vol_prior, 1)

        x = np.arange(n)
        slope = float(np.polyfit(x, np.asarray(values, dtype=float), 1)[0]) if n >= 2 else 0.0
        mean = float(np.mean(values))
        trend_pct = round(slope * n / abs(mean) * 100, 1) if mean else 0.0
        volatility = round(float(np.std(values)) / abs(mean) * 100, 1) if mean else 0.0

        drift_points = [
            {
                "index": position,
                "month": index_labels[position] if position < len(index_labels) else str(position),
                "value": round(float(values[position]), 2),
                "delta_pct": round((values[position] - values[position - 1]) / abs(values[position - 1]) * 100, 1)
                if position > 0 and values[position - 1]
                else None,
            }
            for position in adwin["drift_points"]
        ]

        if adwin["drift_detected"] or (level_pct is not None and abs(level_pct) >= 25):
            status = "shifted"
        elif (
            (level_pct is not None and abs(level_pct) >= 10)
            or (psi or 0) >= 0.1
            or abs(volatility_change) >= 15
        ):
            status = "watch"
        else:
            status = "stable"

        direction = "flat"
        if recent_delta is not None:
            if recent_delta > 2:
                direction = "rising"
            elif recent_delta < -2:
                direction = "falling"

        results.append(
            {
                "kpi": label,
                "column": column,
                "unit": unit,
                "format": fmt,
                "months": index_labels,
                "series": [round(float(value), 2) for value in values],
                "current": round(float(values[-1]), 2),
                "baseline": round(float(np.mean(values[:3])), 2),
                "mean": round(mean, 2),
                "std": round(float(np.std(values)), 2),
                "volatility_pct": volatility,
                "trend_pct": trend_pct,
                "latest_delta_pct": recent_delta,
                "level_pct": level_pct,
                "volatility_change_pp": volatility_change,
                "direction": direction,
                "psi": psi,
                "psi_label": psi_label(psi),
                "distribution": distribution,
                "status": status,
                **{k: adwin[k] for k in ("drift_detected", "drift_score", "n_drift_events", "mean_before", "mean_after", "magnitude_pct")},
                "drift_points": drift_points,
            }
        )

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Feature drift (mix + distribution)
# ─────────────────────────────────────────────────────────────────────────────
CATEGORICAL_FEATURES = [
    ("category", "Product category"),
    ("sub_category", "Sub-category"),
    ("region", "Region"),
    ("segment", "Account segment"),
]


def analyze_feature_drift(df: pd.DataFrame) -> List[Dict]:
    """
    Compare the first 12 months of the history with the most recent 12 months.

    Categorical features use PSI on the mix; order value and discount use PSI on
    quantile bins. This answers "did the *composition* of demand change?" rather
    than "did a total move?".
    """
    if df.empty or "order_date" not in df.columns:
        return []

    work = df.copy()
    work["month"] = work["order_date"].dt.to_period("M").astype(str)
    months = sorted(work["month"].unique())
    if len(months) < 4:
        return []

    window = min(12, max(2, len(months) // 2))
    early_months = set(months[:window])
    recent_months = set(months[-window:])

    early = work[work["month"].isin(early_months)]
    recent = work[work["month"].isin(recent_months)]
    if early.empty or recent.empty:
        return []

    features: List[Dict] = []

    for column, label in CATEGORICAL_FEATURES:
        if column not in work.columns:
            continue
        psi, distribution = psi_categorical(early[column].dropna().astype(str).tolist(), recent[column].dropna().astype(str).tolist())
        if psi is None:
            continue
        biggest = distribution[0] if distribution else None
        change = round(biggest["recent"] - biggest["baseline"], 1) if biggest else 0.0
        features.append(
            {
                "feature": label,
                "key": column,
                "kind": "categorical",
                "psi": psi,
                "status": psi_label(psi),
                "method": "PSI · 12m vs 12m mix",
                "distribution": distribution,
                "summary": (
                    f"{biggest['band']} moved {change:+.1f}pp of the mix (baseline {biggest['baseline']:.1f}% → recent {biggest['recent']:.1f}%)."
                    if biggest else "Distribution available."
                ),
                "baseline_window": f"{months[0]} → {months[window - 1]}",
                "recent_window": f"{months[-window]} → {months[-1]}",
            }
        )

    # Order value distribution
    if "sales" in work.columns:
        psi, distribution = psi_numeric(early["sales"].dropna().tolist(), recent["sales"].dropna().tolist())
        if psi is not None:
            features.append(
                {
                    "feature": "Order line value",
                    "key": "sales",
                    "kind": "numeric",
                    "psi": psi,
                    "status": psi_label(psi),
                    "method": "PSI · quantile bins",
                    "distribution": distribution,
                    "summary": (
                        f"Mean line value moved from ${early['sales'].mean():,.0f} to ${recent['sales'].mean():,.0f} "
                        f"({(recent['sales'].mean() / early['sales'].mean() - 1) * 100:+.1f}%)."
                        if early["sales"].mean() else "Distribution available."
                    ),
                    "baseline_window": f"{months[0]} → {months[window - 1]}",
                    "recent_window": f"{months[-window]} → {months[-1]}",
                }
            )

    # Discount distribution — fixed policy bands are more readable than
    # quantiles here, because a third of the lines carry exactly 0%.
    if "discount" in work.columns:
        bands = [
            (-np.inf, 0.0001, "0%"),
            (0.0001, 0.10, "0–10%"),
            (0.10, 0.20, "10–20%"),
            (0.20, 0.30, "20–30%"),
            (0.30, np.inf, ">30%"),
        ]
        early_values = pd.to_numeric(early["discount"], errors="coerce").dropna().to_numpy()
        recent_values = pd.to_numeric(recent["discount"], errors="coerce").dropna().to_numpy()
        if len(early_values) and len(recent_values):
            early_share = np.array([np.mean((early_values >= low) & (early_values < high)) for low, high, _ in bands])
            recent_share = np.array([np.mean((recent_values >= low) & (recent_values < high)) for low, high, _ in bands])
            psi = round(_safe_psi(early_share, recent_share), 3)
            distribution = [
                {
                    "band": label,
                    "baseline": round(float(early_share[index]) * 100, 1),
                    "recent": round(float(recent_share[index]) * 100, 1),
                }
                for index, (_, _, label) in enumerate(bands)
            ]
            increased = recent["discount"].mean() > early["discount"].mean()
            features.append(
                {
                    "feature": "Discount depth",
                    "key": "discount",
                    "kind": "numeric",
                    "psi": psi,
                    "status": psi_label(psi),
                    "method": "PSI · policy bands",
                    "distribution": distribution,
                    "summary": (
                        f"Average discount moved from {early['discount'].mean() * 100:.1f}% to "
                        f"{recent['discount'].mean() * 100:.1f}% ({'deeper' if increased else 'shallower'})."
                    ),
                    "baseline_window": f"{months[0]} → {months[window - 1]}",
                    "recent_window": f"{months[-window]} → {months[-1]}",
                }
            )

    order = {"significant": 0, "moderate": 1, "stable": 2, "unknown": 3}
    features.sort(key=lambda item: (order.get(item["status"], 3), -item["psi"]))
    return features


# ─────────────────────────────────────────────────────────────────────────────
# BPR rules
# ─────────────────────────────────────────────────────────────────────────────
RULE_METRICS: Dict[str, Dict] = {
    "High Discount Alert": {
        "metric": "high_discount_share",
        "label": "Order lines discounted > 30%",
        "unit": "%",
        "threshold": 15.0,
        "direction": "decrease",
        "method": "post-trigger improvement",
        "rationale": "The rule fires when more than 15% of lines carry a >30% discount; a working rule should shrink that share afterwards.",
    },
    "Low Margin Threshold": {
        "metric": "low_margin_share",
        "label": "Lines under 5% margin (qty > 5)",
        "unit": "%",
        "threshold": 5.5,
        "direction": "decrease",
        "method": "post-trigger improvement",
        "rationale": "High-volume lines below 5% margin should become rarer once pricing review is enforced.",
    },
    "Stockout Prevention": {
        "metric": "revenue_drop_share",
        "label": "Sub-categories down > 30% vs run-rate",
        "unit": "%",
        "threshold": 50.0,
        "direction": "decrease",
        "method": "post-trigger improvement",
        "rationale": "Stockouts show up as sharp sub-category revenue drops; a working rule keeps that share low.",
    },
    "Customer Churn Warning": {
        "metric": "high_value_churn_share",
        "label": "High-value customers churning (90d)",
        "unit": "%",
        "threshold": 70.0,
        "direction": "decrease",
        "method": "post-trigger improvement",
        "rationale": "Among $5k+ customers active in the prior 90 days, the share that stopped buying is the outcome the rule targets.",
    },
    "Seasonal Demand Spike": {
        "metric": "seasonal_index",
        "label": "Revenue vs trailing 3-month run-rate",
        "unit": "×",
        "threshold": 1.4,
        "direction": "increase",
        "method": "coverage",
        "rationale": "When the seasonal index crosses 1.4× the rule pre-authorises stock; coverage measures how often the following month held above the pre-peak run-rate.",
    },
    "Obsolete Product Archive": {
        "metric": "obsolete_product_share",
        "label": "Catalogue with zero orders in 90d",
        "unit": "%",
        "threshold": 75.0,
        "direction": "decrease",
        "method": "post-trigger improvement",
        "rationale": "Archiving should reduce the share of the catalogue that has gone dormant.",
    },
}


def build_rule_metrics(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """Monthly series for every metric referenced by the seeded BPR rules."""
    if df.empty or "order_date" not in df.columns:
        return {}

    work = df.copy()
    work["month"] = work["order_date"].dt.to_period("M").astype(str)
    months = sorted(work["month"].unique())
    metrics: Dict[str, pd.Series] = {}

    if "discount" in work.columns:
        work["_high_discount"] = (pd.to_numeric(work["discount"], errors="coerce").fillna(0) > 0.30).astype(float)
        metrics["high_discount_share"] = work.groupby("month")["_high_discount"].mean().reindex(months) * 100

    if {"profit", "sales", "quantity"}.issubset(work.columns):
        sales = pd.to_numeric(work["sales"], errors="coerce").replace(0, np.nan)
        margin = pd.to_numeric(work["profit"], errors="coerce") / sales
        quantity = pd.to_numeric(work["quantity"], errors="coerce").fillna(0)
        work["_low_margin"] = ((margin < 0.05) & (quantity > 5)).astype(float)
        metrics["low_margin_share"] = work.groupby("month")["_low_margin"].mean().reindex(months) * 100

    if {"sub_category", "sales"}.issubset(work.columns):
        pivot = work.pivot_table(index="month", columns="sub_category", values="sales", aggfunc="sum").fillna(0)
        pivot = pivot.reindex(months).fillna(0)
        trailing = pivot.shift(1).rolling(3).mean()
        drops = (pivot < trailing * 0.7)
        valid = trailing.notna() & (trailing > 0)
        counts = valid.sum(axis=1).replace(0, np.nan)
        metrics["revenue_drop_share"] = (drops & valid).sum(axis=1) / counts * 100

    totals = work.groupby("month")["sales"].sum().reindex(months)
    trailing_total = totals.shift(1).rolling(3).mean()
    metrics["seasonal_index"] = totals / trailing_total.replace(0, np.nan)

    # Rolling 90-day churn among high-value customers, evaluated as of each month
    # end: of the $5k+ customers active in the prior 90 days, how many stopped
    # buying? This stays comparable across the whole history.
    if {"customer_id", "order_date", "sales"}.issubset(work.columns):
        churn_share = {}
        obsolete_share = {}
        spend = work.groupby("customer_id")["sales"].sum()
        high_value = set(spend[spend >= 5000].index)

        for month in months:
            end = pd.Period(month, freq="M").end_time
            history = work[work["order_date"] <= end]
            if history.empty or not high_value:
                continue

            previous_ids = set(
                history[
                    (history["order_date"] > end - pd.Timedelta(days=180))
                    & (history["order_date"] <= end - pd.Timedelta(days=90))
                    & (history["customer_id"].isin(high_value))
                ]["customer_id"]
            )
            current_ids = set(
                history[
                    (history["order_date"] > end - pd.Timedelta(days=90))
                    & (history["customer_id"].isin(high_value))
                ]["customer_id"]
            )
            if previous_ids:
                churn_share[month] = round(len(previous_ids - current_ids) / len(previous_ids) * 100, 2)

            if "product_name" in history.columns:
                ever = history["product_name"].nunique()
                active = history[history["order_date"] > end - pd.Timedelta(days=90)]["product_name"].nunique()
                if ever:
                    obsolete_share[month] = round((ever - active) / ever * 100, 2)

        metrics["high_value_churn_share"] = pd.Series(churn_share).reindex(months)
        metrics["obsolete_product_share"] = pd.Series(obsolete_share).reindex(months)

    return metrics


def evaluate_bpr_rules(rules: List[Dict], df: pd.DataFrame) -> List[Dict]:
    """
    Attach a measured evaluation block to every rule.

    ``effectiveness_score`` is only populated when there are enough historical
    triggers to measure it; otherwise it stays ``None`` and the UI says so rather
    than showing a made-up number.
    """
    metrics = build_rule_metrics(df)
    evaluated: List[Dict] = []

    for rule in rules:
        entry = dict(rule)
        meta = RULE_METRICS.get(rule.get("rule_name", ""))

        if not meta or meta["metric"] not in metrics or metrics[meta["metric"]].dropna().empty:
            entry["evaluation"] = {
                "metric": None,
                "label": None,
                "unit": None,
                "threshold": None,
                "direction": None,
                "method": "not measurable with this dataset",
                "triggers": 0,
                "trigger_rate": 0.0,
                "sample_size": 0,
                "effectiveness": None,
                "current_value": None,
                "current_triggered": False,
                "improving": None,
                "last_triggered": None,
                "trigger_history": [],
                "rationale": "Rule refers to inventory, catalog or process data that is not present in the orders dataset.",
                "months_evaluated": 0,
            }
            entry["effectiveness_score"] = None
            evaluated.append(entry)
            continue

        series = metrics[meta["metric"]].dropna()
        series = series[series.index.isin(metrics[meta["metric"]].index)]
        values = series.to_list()
        labels = series.index.to_list()
        threshold = meta["threshold"]

        if meta["metric"] == "seasonal_index":
            triggered_flags = [value >= threshold for value in values]
        else:
            triggered_flags = [value > threshold for value in values]

        triggered_months = [labels[i] for i, flag in enumerate(triggered_flags) if flag]

        improvements: List[float] = []
        coverage_hits = 0
        coverage_samples = 0

        if meta["method"] == "coverage":
            # Did the month after a seasonal spike hold above the pre-peak run-rate?
            for index, flag in enumerate(triggered_flags):
                if not flag or index + 1 >= len(values):
                    continue
                baseline = float(np.mean(values[max(0, index - 3):index])) if index else float(np.mean(values[: max(index, 1)]))
                if baseline <= 0:
                    continue
                coverage_samples += 1
                if values[index + 1] >= baseline:
                    coverage_hits += 1
            effectiveness = round(coverage_hits / coverage_samples, 2) if coverage_samples else None
        else:
            for index, flag in enumerate(triggered_flags):
                if not flag or index + 3 >= len(values):
                    continue
                base = values[index]
                if not base or pd.isna(base):
                    continue
                post = float(np.nanmean(values[index + 1:index + 3]))
                if meta["direction"] == "decrease":
                    improvements.append((base - post) / abs(base))
                else:
                    improvements.append((post - base) / abs(base))
            effectiveness = (
                round(min(0.98, max(0.05, 0.5 + float(np.mean(improvements)))), 2)
                if improvements else None
            )

        recent = values[-1] if values else None
        prior = float(np.mean(values[-4:-1])) if len(values) >= 4 else None
        if recent is not None and prior:
            improving = recent < prior if meta["direction"] == "decrease" else recent > prior
        else:
            improving = None

        trigger_history = [
            {"month": labels[i], "value": round(float(values[i]), 2), "triggered": bool(triggered_flags[i])}
            for i in range(len(labels))
        ]

        entry["effectiveness_score"] = effectiveness
        entry["evaluation"] = {
            "metric": meta["metric"],
            "label": meta["label"],
            "unit": meta["unit"],
            "threshold": threshold,
            "direction": meta["direction"],
            "method": meta["method"],
            "triggers": len(triggered_months),
            "trigger_rate": round(len(triggered_months) / max(len(values), 1) * 100, 1),
            "sample_size": coverage_samples if meta["method"] == "coverage" else len(improvements),
            "effectiveness": effectiveness,
            "current_value": round(float(values[-1]), 2) if values else None,
            "current_triggered": bool(triggered_flags[-1]) if triggered_flags else False,
            "improving": improving,
            "last_triggered": triggered_months[-1] if triggered_months else None,
            "trigger_history": trigger_history,
            "rationale": meta["rationale"],
            "months_evaluated": len(values),
        }
        evaluated.append(entry)

    return evaluated
