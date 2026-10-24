"""
Root Cause Analysis engine.

Three stages, all computed from the loaded order history:

1. ``detect_anomalies`` — multiplicative month-of-year factors remove recurring
   seasonality, a centred 12-month median gives the run-rate, and robust z-scores
   (median / MAD) flag months that deviate from that expectation.
2. ``explain_anomaly`` — decomposes the gap into volume vs price, discount/margin,
   customer mix and dimension contributions (category / sub-category / region /
   account segment), always against a **seasonally matched** run-rate built from
   the three preceding months so the explanation agrees with the detector.
3. ``build_fishbone`` — turns the measured drivers into an Ishikawa tree with
   confidence proportional to the share of the gap each factor explains.

Confidence is always in 0..1 and relative to the observed gap; evidence strings
always carry the numbers used to compute them.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

COMPARISON_MONTHS = 3
MIN_HISTORY = 6  # months of history required before a month can be judged


# ── helpers ──────────────────────────────────────────────────────────────────
def _robust_scale(values: np.ndarray) -> tuple[float, float]:
    """Median and a robust sigma estimate (MAD → normal-consistent)."""
    values = np.asarray(values, dtype=float)
    values = values[~np.isnan(values)]
    if len(values) == 0:
        return 0.0, 1.0
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    scale = 1.4826 * mad
    if scale <= 1e-9:
        scale = float(np.std(values))
    if scale <= 1e-9:
        scale = max(abs(median) * 0.1, 1.0)
    return median, scale


def _pct_change(current: float, previous: float) -> Optional[float]:
    if previous == 0 or pd.isna(previous):
        return None
    return round((current - previous) / abs(previous) * 100, 1)


def _money(value: float) -> float:
    return round(float(value), 2)


def _signed_money(value: float) -> str:
    return f"{'-' if value < 0 else '+'}${abs(float(value)):,.0f}"


def _month_factors(month_labels, values) -> Dict[int, float]:
    """
    Multiplicative month-of-year factors estimated from a detrended series.

    Each month's value is divided by a centred 12-month mean; the median of those
    ratios across years is the seasonal factor (clipped to 0.55–1.8 so one odd
    year cannot dominate).
    """
    labels = pd.Series(list(month_labels)).astype(str)
    dates = pd.to_datetime(labels + "-01", errors="coerce")
    calendar = dates.dt.month.to_numpy()
    series = pd.Series(np.asarray(values, dtype=float))

    trend = series.rolling(12, center=True, min_periods=6).mean()
    detrended = (series / trend.replace(0, np.nan)).to_numpy()

    factors: Dict[int, float] = {}
    for month_number in range(1, 13):
        subset = detrended[calendar == month_number]
        subset = subset[~np.isnan(subset)]
        if len(subset):
            factors[month_number] = float(np.clip(np.median(subset), 0.55, 1.8))
    return factors


# ── 1. anomaly detection ─────────────────────────────────────────────────────
def seasonal_baseline(monthly: pd.DataFrame) -> pd.DataFrame:
    """
    Expected revenue per month = deseasonalised run-rate × month-of-year factor.

    ``monthly`` needs ``month`` (YYYY-MM string) and ``value``.
    """
    work = monthly.copy()
    work["value"] = pd.to_numeric(work["value"], errors="coerce").fillna(0.0)
    values = work["value"].astype(float)

    dates = pd.to_datetime(work["month"].astype(str) + "-01", errors="coerce")
    calendar = dates.dt.month.to_numpy()

    if len(values) >= 12 and not pd.isna(calendar).all():
        factors = _month_factors(work["month"], values)
        seasonal = np.array([factors.get(int(month), 1.0) for month in calendar])
        deseasonalized = values / seasonal
        run_rate = deseasonalized.rolling(12, center=True, min_periods=6).median()
        expected = (run_rate * seasonal).to_numpy()
        fallback = float(values.median())
        expected = np.where(np.isnan(expected), fallback, expected)
    else:
        factors = {}
        seasonal = np.ones(len(values))
        expected = np.zeros(len(values))
        for index in range(len(values)):
            prior = values.to_numpy()[max(0, index - COMPARISON_MONTHS): index]
            expected[index] = float(np.median(prior)) if len(prior) else float(values.iloc[index])

    residual = values.to_numpy() / np.where(expected == 0, np.nan, expected)
    valid = residual[~np.isnan(residual)]
    median, scale = _robust_scale(valid if len(valid) else np.array([1.0]))
    z_scores = np.nan_to_num((residual - median) / scale, nan=0.0)

    return pd.DataFrame(
        {
            "month": work["month"].astype(str).to_numpy(),
            "value": values.to_numpy(),
            "expected": expected,
            "seasonal_index": seasonal,
            "z_score": z_scores,
            "factors": [factors.get(int(month), 1.0) for month in calendar],
        }
    )


def detect_anomalies(monthly: pd.DataFrame, threshold: float = 2.0, min_history: int = MIN_HISTORY) -> List[Dict]:
    """Flag months whose revenue is unusual once trend and seasonality are removed."""
    if len(monthly) < 4:
        return []

    enriched = seasonal_baseline(monthly)
    rows: List[Dict] = []

    for index, row in enumerate(enriched.itertuples(index=False)):
        if index < min_history:
            # Not enough history for a meaningful run-rate — do not call the
            # ramp-up months anomalies.
            continue

        value = float(row.value)
        expected = float(row.expected)
        gap = value - expected
        gap_pct = _pct_change(value, expected)
        z = float(row.z_score)

        flagged = abs(z) >= threshold
        if not flagged and gap_pct is not None and gap_pct <= -30:
            flagged = True
        if not flagged:
            continue

        anomaly_type = "drop" if gap < 0 else "spike"
        severity = "high" if abs(z) >= 3 or (gap_pct or 0) <= -40 else "medium" if abs(z) >= 2.5 else "low"
        rows.append(
            {
                "month": str(row.month),
                "value": _money(value),
                "expected": _money(expected),
                "gap": _money(gap),
                "gap_pct": gap_pct,
                "z_score": round(z, 2),
                "seasonal_index": round(float(row.seasonal_index), 2),
                "type": anomaly_type,
                "severity": severity,
            }
        )

    return rows


# ── 2. driver decomposition ──────────────────────────────────────────────────
def _dimension_drivers(
    current: pd.DataFrame,
    comparison: pd.DataFrame,
    column: str,
    limit: int = 6,
) -> List[Dict]:
    """Weighted contribution of each value of ``column`` to the gap."""
    if column not in current.columns or comparison.empty:
        return []

    cur = current.groupby(column, dropna=False)["sales"].sum()
    weighted = comparison["sales"] * comparison["weight"]
    comp = weighted.groupby(comparison[column], dropna=False).sum()

    rows: List[Dict] = []
    for label in cur.index.union(comp.index):
        current_value = float(cur.get(label, 0.0))
        baseline_value = float(comp.get(label, 0.0))
        contribution = current_value - baseline_value
        if abs(contribution) < 1:
            continue
        rows.append(
            {
                "label": str(label) if label is not None and str(label) != "nan" else "Unknown",
                "current": _money(current_value),
                "baseline": _money(baseline_value),
                "contribution": _money(contribution),
                "change_pct": _pct_change(current_value, baseline_value),
            }
        )

    rows.sort(key=lambda item: item["contribution"])
    return rows[:limit]


def explain_anomaly(df: pd.DataFrame, month: str, limit: int = 6, expected: Optional[float] = None) -> Optional[Dict]:
    """
    Explain one month against a seasonally matched run-rate.

    The comparison level for month M is the average of the three preceding
    months, each scaled by ``seasonal_factor(M) / seasonal_factor(that month)``.
    That makes the comparison seasonal-neutral *and* additive, so every driver
    below sums back to the gap the anomaly detector reported.
    """
    if df.empty or "order_date" not in df.columns:
        return None

    work = df.copy()
    work["month"] = work["order_date"].dt.to_period("M").astype(str)

    month_period = pd.Period(month, freq="M")
    month_start = month_period.start_time
    month_end = month_period.end_time

    current = work[work["month"] == month]
    if current.empty:
        return None

    monthly_totals = work.groupby("month")["sales"].sum().sort_index()
    factors = _month_factors(monthly_totals.index.tolist(), monthly_totals.values)
    target_factor = factors.get(month_period.month, 1.0)

    prior_labels = [str(month_period - offset) for offset in range(1, COMPARISON_MONTHS + 1)]
    comparison = work[work["month"].isin(prior_labels)].copy()

    if comparison.empty:
        comparison = current.copy()
        comparison["weight"] = 1.0
    else:
        n_prior = max(int(comparison["month"].nunique()), 1)
        comparison["weight"] = (
            comparison["order_date"].dt.month.map(lambda value: target_factor / factors.get(int(value), 1.0))
            / n_prior
        )

    # Align the comparison level with the detector's expectation so the drivers
    # sum to exactly the gap shown on the anomaly card.
    raw_comp = float((comparison["sales"] * comparison["weight"]).sum())
    if expected and raw_comp > 0:
        comparison["weight"] *= float(expected) / raw_comp

    weight = comparison["weight"]
    weight_sum = float(weight.sum())

    cur_sales = float(current["sales"].sum())
    comp_sales = float((comparison["sales"] * weight).sum())
    gap = cur_sales - comp_sales

    cur_orders = int(current["order_id"].nunique())
    comp_orders = float(comparison.groupby("order_id")["weight"].first().sum())
    cur_aov = cur_sales / cur_orders if cur_orders else 0.0
    comp_aov = comp_sales / comp_orders if comp_orders else 0.0

    # First-order decomposition: Δrevenue ≈ Δorders·AOV_base + ΔAOV·orders_now
    volume_effect = (cur_orders - comp_orders) * comp_aov
    price_effect = (cur_aov - comp_aov) * cur_orders
    mix_effect = gap - volume_effect - price_effect

    def effect(value: float) -> Dict:
        return {
            "value": _money(value),
            "share": round(value / gap * 100, 1) if gap else 0.0,
        }

    cur_discount = float(current["discount"].mean()) if "discount" in current.columns else 0.0
    comp_discount = (
        float((comparison["discount"] * weight).sum() / weight_sum) if weight_sum and "discount" in comparison.columns else 0.0
    )
    discount_effect = -cur_sales * (cur_discount - comp_discount)

    cur_profit = float(current["profit"].sum())
    comp_profit = float((comparison["profit"] * weight).sum())
    cur_margin = cur_profit / cur_sales * 100 if cur_sales else 0.0
    comp_margin = comp_profit / comp_sales * 100 if comp_sales else 0.0

    # Customer mix
    first_order = work.groupby("customer_id")["order_date"].min()
    new_ids = set(first_order[(first_order >= month_start) & (first_order <= month_end)].index)
    new_revenue = float(current[current["customer_id"].isin(new_ids)]["sales"].sum())

    comp_start = comparison["order_date"].min() if not comparison.empty else month_start
    comp_new_ids = set(first_order[(first_order >= comp_start) & (first_order < month_start)].index)
    comp_new_mask = comparison["customer_id"].isin(comp_new_ids)
    comp_new_revenue = float((comparison.loc[comp_new_mask, "sales"] * comparison.loc[comp_new_mask, "weight"]).sum())
    comp_returning = comp_sales - comp_new_revenue

    by_customer = current.groupby("customer_id")["sales"].sum().sort_values(ascending=False)
    top10_revenue = float(by_customer.head(10).sum())
    top10_share = float(top10_revenue / cur_sales * 100) if cur_sales else 0.0

    cur_lag = float(current["ship_lag_days"].mean()) if "ship_lag_days" in current.columns else 0.0
    comp_lag = (
        float((comparison["ship_lag_days"] * weight).sum() / weight_sum)
        if weight_sum and "ship_lag_days" in comparison.columns
        else 0.0
    )

    drivers = {
        "volume": {**effect(volume_effect), "orders": cur_orders, "baseline_orders": round(comp_orders, 1)},
        "price": {
            **effect(price_effect),
            "aov": _money(cur_aov),
            "baseline_aov": _money(comp_aov),
            "change_pct": _pct_change(cur_aov, comp_aov),
        },
        "mix": effect(mix_effect),
        "discount": {
            "current": round(cur_discount * 100, 1),
            "baseline": round(comp_discount * 100, 1),
            "change_pp": round((cur_discount - comp_discount) * 100, 1),
            "profit_effect": _money(discount_effect),
        },
        "margin": {
            "current": round(cur_margin, 1),
            "baseline": round(comp_margin, 1),
            "change_pp": round(cur_margin - comp_margin, 1),
            "profit": _money(cur_profit),
        },
        "customers": {
            "new": int(len(new_ids)),
            "new_revenue": _money(new_revenue),
            "new_revenue_baseline": _money(comp_new_revenue),
            "new_revenue_share": round(new_revenue / cur_sales * 100, 1) if cur_sales else 0.0,
            "returning_revenue": _money(cur_sales - new_revenue),
            "returning_revenue_baseline": _money(comp_returning),
            "top10_share": round(top10_share, 1),
            "top10_revenue": _money(top10_revenue),
        },
        "delivery": {
            "current_lag": round(cur_lag, 1),
            "baseline_lag": round(comp_lag, 1),
            "change_days": round(cur_lag - comp_lag, 1),
        },
        "seasonality": {
            "calendar_month": int(month_period.month),
            "factor": round(target_factor, 2),
            "index": round(cur_sales / comp_sales, 2) if comp_sales else None,
        },
        "orders": {"current": cur_orders, "baseline": round(comp_orders, 1)},
        "revenue": {"current": _money(cur_sales), "baseline": _money(comp_sales), "gap": _money(gap)},
    }

    dimensions = {
        "category": _dimension_drivers(current, comparison, "category", 4),
        "sub_category": _dimension_drivers(current, comparison, "sub_category", limit),
        "region": _dimension_drivers(current, comparison, "region", 4),
        "segment": _dimension_drivers(current, comparison, "customer_segment", 3),
        "product": _dimension_drivers(current, comparison, "product_name", 5),
    }

    worst_category = min(dimensions["category"], key=lambda item: item["contribution"], default=None)
    worst_subcategory = min(dimensions["sub_category"], key=lambda item: item["contribution"], default=None)

    direction = "fell" if gap < 0 else "rose"
    narrative = (
        f"{month} revenue {direction} to ${cur_sales:,.0f}, "
        f"${abs(gap):,.0f} {'below' if gap < 0 else 'above'} the seasonally matched "
        f"${comp_sales:,.0f} run-rate."
    )
    if worst_category and worst_category["contribution"] < 0:
        narrative += (
            f" {worst_category['label']} contributed ${abs(worst_category['contribution']):,.0f} of the shortfall"
            + (f", led by {worst_subcategory['label']}." if worst_subcategory and worst_subcategory["contribution"] < 0 else ".")
        )
    if abs(discount_effect) >= 500:
        narrative += (
            f" Discounts averaged {cur_discount * 100:.1f}% versus {comp_discount * 100:.1f}%, "
            f"costing roughly ${abs(discount_effect):,.0f} of profit."
        )

    return {
        "month": month,
        "revenue": drivers["revenue"],
        "effects": {"volume": effect(volume_effect), "price": effect(price_effect), "mix": effect(mix_effect)},
        "drivers": drivers,
        "dimensions": dimensions,
        "narrative": narrative,
    }


# ── 3. fishbone ──────────────────────────────────────────────────────────────
def build_fishbone(df: pd.DataFrame, explanation: Optional[Dict]) -> Dict:
    """
    Build an Ishikawa tree from the measured drivers of the selected anomaly.

    Each factor carries a confidence (share of the gap it can explain, capped),
    a dollar impact where one can be quantified, and evidence text with numbers.
    """
    if explanation is None:
        return {"fishbone": {}, "top_root_cause": None}

    rev = explanation["revenue"]
    gap = rev["gap"] or 0.0
    gap_abs = abs(gap) or 1.0
    dims = explanation["dimensions"]
    drivers = explanation["drivers"]
    cust = drivers["customers"]

    def share_conf(value: float, ceiling: float = 0.95) -> float:
        return round(min(ceiling, max(0.05, abs(value) / gap_abs * 0.9)), 2)

    # ── Product ──────────────────────────────────────────────────────────────
    worst_cat = min(dims["category"], key=lambda item: item["contribution"], default=None)
    worst_sub = min(dims["sub_category"], key=lambda item: item["contribution"], default=None)

    if worst_cat:
        product_conf = share_conf(worst_cat["contribution"])
        product_evidence = (
            f"{worst_cat['label']} revenue was ${worst_cat['current']:,.0f} vs a "
            f"${worst_cat['baseline']:,.0f} seasonal run-rate ({worst_cat['change_pct']:+.1f}%), "
            f"a ${abs(worst_cat['contribution']):,.0f} contribution to the gap."
        )
        if worst_sub and worst_sub["contribution"] < 0:
            product_evidence += (
                f" Worst sub-category: {worst_sub['label']} at ${worst_sub['current']:,.0f} "
                f"vs ${worst_sub['baseline']:,.0f}."
            )
        product_impact = worst_cat["contribution"]
    else:
        product_conf, product_impact = 0.1, 0.0
        product_evidence = "No single category dominates the movement; the change is broad-based."

    disc = drivers["discount"]
    discount_impact = disc["profit_effect"]
    discount_conf = share_conf(discount_impact, 0.8)
    discount_evidence = (
        f"Average discount moved {disc['change_pp']:+.1f}pp to {disc['current']:.1f}% "
        f"(baseline {disc['baseline']:.1f}%), an estimated ${abs(discount_impact):,.0f} profit swing at current volume."
    )

    # ── Process ──────────────────────────────────────────────────────────────
    delivery = drivers["delivery"]
    lag_delta = delivery["change_days"]
    delivery_conf = round(min(0.85, max(0.05, abs(lag_delta) / 3.0)), 2)
    delivery_evidence = (
        f"Average ship lag was {delivery['current_lag']:.1f} days vs {delivery['baseline_lag']:.1f} days "
        f"in the comparison window ({lag_delta:+.1f} days)."
    )

    concentration = cust["top10_share"]
    # Concentration is a standing risk, not an explanation of this month's gap,
    # so its confidence is capped below the measured drivers.
    concentration_conf = round(min(0.55, max(0.05, (concentration - 15) / 90)), 2)
    concentration_evidence = (
        f"Top 10 customers generated ${cust['top10_revenue']:,.0f} — {concentration:.1f}% of the "
        f"month's ${rev['current']:,.0f} revenue across {drivers['orders']['current']} orders."
    )

    # ── People ───────────────────────────────────────────────────────────────
    new_rev_delta = cust["new_revenue"] - cust["new_revenue_baseline"]
    acquisition_conf = share_conf(new_rev_delta, 0.9)
    acquisition_evidence = (
        f"New-customer revenue was ${cust['new_revenue']:,.0f} ({cust['new_revenue_share']:.1f}% of the month) "
        f"versus a ${cust['new_revenue_baseline']:,.0f} seasonal run-rate, a swing of {_signed_money(new_rev_delta)}."
    )

    returning_delta = cust["returning_revenue"] - cust["returning_revenue_baseline"]
    retention_conf = share_conf(returning_delta, 0.88)
    retention_evidence = (
        f"Returning-customer revenue was ${cust['returning_revenue']:,.0f} versus "
        f"${cust['returning_revenue_baseline']:,.0f} normally ({_signed_money(returning_delta)})."
    )

    # ── External ─────────────────────────────────────────────────────────────
    season = drivers["seasonality"]
    season_index = season["index"]
    if season_index:
        season_conf = round(min(0.9, max(0.05, abs(season_index - 1) * 1.2)), 2)
        season_evidence = (
            f"Revenue was {season_index:.2f}× the seasonally matched run-rate for "
            f"{pd.Timestamp(2024, season['calendar_month'], 1).strftime('%B')} "
            f"(month-of-year factor {season['factor']:.2f})."
        )
        season_impact = rev["current"] - rev["baseline"]
    else:
        season_conf, season_impact = 0.1, 0.0
        season_evidence = "Not enough years in the dataset to separate seasonality from the movement."

    margin = drivers["margin"]
    margin_delta = margin["change_pp"]
    margin_impact = rev["current"] * margin_delta / 100
    competition_conf = round(min(0.85, max(0.05, abs(margin_delta) / 4.0)), 2)
    competition_evidence = (
        f"Gross margin was {margin['current']:.1f}% versus {margin['baseline']:.1f}% "
        f"({margin_delta:+.1f}pp), a ${abs(margin_impact):,.0f} profit difference on the month's revenue."
    )

    causes = {
        "Product": [
            {
                "factor": "Category revenue shortfall",
                "confidence": product_conf,
                "impact": _money(product_impact),
                "evidence": product_evidence,
            },
            {
                "factor": "Discount over-reliance",
                "confidence": discount_conf,
                "impact": _money(discount_impact),
                "evidence": discount_evidence,
            },
        ],
        "Process": [
            {
                "factor": "Delivery delays",
                "confidence": delivery_conf,
                "impact": 0.0,
                "evidence": delivery_evidence,
            },
            {
                "factor": "Customer concentration risk",
                "confidence": concentration_conf,
                "impact": 0.0,
                "evidence": concentration_evidence,
            },
        ],
        "People": [
            {
                "factor": "New-customer acquisition drop",
                "confidence": acquisition_conf,
                "impact": _money(new_rev_delta),
                "evidence": acquisition_evidence,
            },
            {
                "factor": "Returning-customer softness",
                "confidence": retention_conf,
                "impact": _money(returning_delta),
                "evidence": retention_evidence,
            },
        ],
        "External": [
            {
                "factor": "Seasonal demand shift",
                "confidence": season_conf,
                "impact": _money(season_impact),
                "evidence": season_evidence,
            },
            {
                "factor": "Margin compression",
                "confidence": competition_conf,
                "impact": _money(margin_impact),
                "evidence": competition_evidence,
            },
        ],
    }

    ranked = [(branch, cause) for branch, items in causes.items() for cause in items]
    top_branch, top = max(
        ranked,
        key=lambda item: item[1]["confidence"] * (1 + abs(item[1]["impact"]) / gap_abs),
    )

    return {
        "fishbone": causes,
        "top_root_cause": {
            "branch": top_branch,
            "factor": top["factor"],
            "confidence": top["confidence"],
            "impact": top["impact"],
            "evidence": top["evidence"],
        },
    }
