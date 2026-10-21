"""
Analysis router — Deep org-level intelligence report.

Endpoints:
  GET /api/analysis/report       — Full analysis: KPIs, segmentation, drift, root cause, forecast, AI strategy
  GET /api/analysis/health-score — Single 0-100 org-health score
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import func
from db.database import SessionLocal
from db.models import Order, Customer, KPI, DatasetMeta
from ml.root_cause import detect_anomalies, build_fishbone

import pandas as pd
import numpy as np
from datetime import datetime
from collections import Counter, defaultdict

router = APIRouter()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_orders_df(db) -> pd.DataFrame:
    orders = db.query(Order).all()
    if not orders:
        return pd.DataFrame()
    return pd.DataFrame([{
        "order_id":    o.order_id,
        "order_date":  pd.to_datetime(o.order_date),
        "ship_date":   pd.to_datetime(o.ship_date) if o.ship_date else None,
        "customer_id": o.customer_id,
        "category":    o.category,
        "sub_category": o.sub_category,
        "sales":       o.sales or 0.0,
        "profit":      o.profit or 0.0,
        "quantity":    o.quantity or 1,
        "discount":    o.discount or 0.0,
    } for o in orders])


def _compute_kpis(df: pd.DataFrame) -> dict:
    """Compute KPI values entirely from the orders DataFrame."""
    if df.empty:
        return {}

    total_sales    = float(df["sales"].sum())
    total_profit   = float(df["profit"].sum())
    unique_orders  = df["order_id"].nunique()
    unique_custs   = df["customer_id"].nunique()
    aov            = total_sales / unique_orders if unique_orders else 0.0
    margin_pct     = (total_profit / total_sales * 100) if total_sales else 0.0

    cust_counts = Counter(df["customer_id"])
    repeat_custs = sum(1 for v in cust_counts.values() if v > 1)
    repeat_rate  = repeat_custs / unique_custs * 100 if unique_custs else 0.0

    # Baseline = first-half period average, current = second-half
    df_sorted = df.sort_values("order_date")
    mid = len(df_sorted) // 2
    first_half  = df_sorted.iloc[:mid]
    second_half = df_sorted.iloc[mid:]

    def _half_metric(half, col):
        return float(half[col].sum()) if not half.empty else 0.0

    base_sales  = _half_metric(first_half, "sales")
    base_profit = _half_metric(first_half, "profit")
    base_aov    = base_sales / max(1, first_half["order_id"].nunique())
    base_margin = (base_profit / base_sales * 100) if base_sales else 0.0

    return {
        "total_revenue":      {"value": round(total_sales, 2),   "baseline": round(base_sales, 2),    "target": round(total_sales * 1.10, 2),  "unit": "USD"},
        "total_profit":       {"value": round(total_profit, 2),  "baseline": round(base_profit, 2),   "target": round(total_profit * 1.15, 2), "unit": "USD"},
        "total_orders":       {"value": unique_orders,           "baseline": first_half["order_id"].nunique(), "target": round(unique_orders * 1.10), "unit": "count"},
        "unique_customers":   {"value": unique_custs,            "baseline": first_half["customer_id"].nunique(), "target": round(unique_custs * 1.12), "unit": "count"},
        "avg_order_value":    {"value": round(aov, 2),           "baseline": round(base_aov, 2),      "target": round(aov * 1.08, 2),          "unit": "USD"},
        "profit_margin_pct":  {"value": round(margin_pct, 2),    "baseline": round(base_margin, 2),   "target": round(margin_pct * 1.20, 2),   "unit": "%"},
        "repeat_rate_pct":    {"value": round(repeat_rate, 2),   "baseline": round(repeat_rate * 0.95, 2), "target": round(min(100, repeat_rate * 1.15), 2), "unit": "%"},
    }


def _compute_segmentation(df: pd.DataFrame) -> list:
    """RFM-based segmentation — Champion / At-Risk / New-Growing / Lost."""
    if df.empty or "customer_id" not in df.columns:
        return []

    now = df["order_date"].max()
    rfm = df.groupby("customer_id").agg(
        recency=("order_date", lambda x: (now - x.max()).days),
        frequency=("order_id", "nunique"),
        monetary=("sales", "sum"),
    ).reset_index()

    # Percentile-based scoring (1-4)
    for col in ["recency", "frequency", "monetary"]:
        try:
            rfm[f"{col}_score"] = pd.qcut(rfm[col], 4, labels=[4, 3, 2, 1] if col == "recency" else [1, 2, 3, 4], duplicates="drop")
        except Exception:
            rfm[f"{col}_score"] = 2

    rfm["rfm_score"] = rfm["recency_score"].astype(int) + rfm["frequency_score"].astype(int) + rfm["monetary_score"].astype(int)

    def _segment(row):
        score = row["rfm_score"]
        freq  = row["frequency"]
        rec   = row["recency"]
        if score >= 10 and freq >= 3:
            return "Champions"
        elif rec <= 90 and freq >= 2:
            return "Loyal"
        elif rec > 180 and freq >= 2:
            return "At-Risk"
        elif re := rec <= 60 and freq == 1:  # noqa
            return "New"
        elif freq == 1 and rec <= 60:
            return "New"
        elif rec > 270:
            return "Lost"
        else:
            return "Potential"

    rfm["segment"] = rfm.apply(_segment, axis=1)
    
    result = []
    for seg, grp in rfm.groupby("segment"):
        result.append({
            "segment":       seg,
            "customer_count": int(len(grp)),
            "avg_spend":     round(float(grp["monetary"].mean()), 2),
            "avg_frequency": round(float(grp["frequency"].mean()), 2),
            "avg_recency_days": round(float(grp["recency"].mean()), 0),
        })
    return sorted(result, key=lambda x: -x["customer_count"])


def _compute_drift_series(df: pd.DataFrame) -> list:
    """Monthly KPI series for drift visualisation."""
    if df.empty:
        return []
    df["month"] = df["order_date"].dt.to_period("M").astype(str)
    monthly = df.groupby("month").agg(
        revenue=("sales", "sum"),
        profit=("profit", "sum"),
        orders=("order_id", "nunique"),
        customers=("customer_id", "nunique"),
    ).reset_index()
    monthly["aov"] = monthly["revenue"] / monthly["orders"].replace(0, np.nan)
    monthly["margin_pct"] = monthly["profit"] / monthly["revenue"].replace(0, np.nan) * 100

    return [
        {
            "month":    row["month"],
            "revenue":  round(float(row["revenue"]), 2),
            "profit":   round(float(row["profit"]), 2),
            "orders":   int(row["orders"]),
            "customers": int(row["customers"]),
            "aov":      round(float(row["aov"]) if not pd.isna(row["aov"]) else 0, 2),
            "margin_pct": round(float(row["margin_pct"]) if not pd.isna(row["margin_pct"]) else 0, 2),
        }
        for _, row in monthly.sort_values("month").iterrows()
    ]


def _compute_forecast(df: pd.DataFrame, horizon: int = 6) -> list:
    """Simple linear-trend forecast for the next `horizon` months."""
    if df.empty:
        return []
    df["month"] = df["order_date"].dt.to_period("M").astype(str)
    monthly = df.groupby("month")["sales"].sum().reset_index().sort_values("month")
    y = monthly["sales"].values.astype(float)
    if len(y) < 3:
        return []

    x = np.arange(len(y))
    coeffs = np.polyfit(x, y, 1)
    slope, intercept = coeffs
    last_period = pd.Period(monthly["month"].iloc[-1], "M")

    forecast = []
    for i in range(1, horizon + 1):
        pred = float(slope * (len(y) + i - 1) + intercept)
        pred = max(0, pred)
        std_resid = float(np.std(y - np.polyval(coeffs, x)))
        forecast.append({
            "month":      str(last_period + i),
            "predicted":  round(pred, 2),
            "lower":      round(max(0, pred - 1.96 * std_resid), 2),
            "upper":      round(pred + 1.96 * std_resid, 2),
        })
    return forecast


def _compute_health_score(kpis: dict, segmentation: list, anomalies: list, df: pd.DataFrame) -> float:
    """
    Composite 0-100 org health score.
    Weights: revenue trend (35), margin trend (25), customer health (20), anomaly penalty (20)
    """
    if not kpis:
        return 50.0

    score = 0.0

    # Revenue trend (35 pts)
    rev = kpis.get("total_revenue", {})
    if rev.get("baseline", 0) > 0:
        rev_ratio = rev["value"] / rev["baseline"]
        score += min(35, max(0, (rev_ratio - 0.7) / 0.6 * 35))
    else:
        score += 15

    # Margin trend (25 pts)
    mgn = kpis.get("profit_margin_pct", {})
    if mgn.get("value", 0) > 0:
        mgn_ratio = mgn["value"] / max(0.1, mgn.get("baseline", mgn["value"]))
        score += min(25, max(0, mgn_ratio * 20))
    else:
        score += 5

    # Customer health — Champions share (20 pts)
    total_seg_custs = sum(s["customer_count"] for s in segmentation)
    champions = next((s for s in segmentation if s["segment"] == "Champions"), None)
    if champions and total_seg_custs:
        champ_share = champions["customer_count"] / total_seg_custs
        score += min(20, champ_share * 50)
    else:
        score += 8

    # Anomaly penalty (20 pts — start full, deduct per anomaly)
    anomaly_penalty = min(20, len(anomalies) * 4)
    score += max(0, 20 - anomaly_penalty)

    return round(min(100, max(0, score)), 1)


def _compute_benchmarks(kpis: dict, df: pd.DataFrame) -> list:
    """Industry benchmark comparison — uses data quartiles as proxy benchmarks."""
    if df.empty or not kpis:
        return []
    results = []
    rev = kpis.get("total_revenue", {})
    mgn = kpis.get("profit_margin_pct", {})
    rpt = kpis.get("repeat_rate_pct", {})
    aov = kpis.get("avg_order_value", {})

    monthly_rev = df.groupby(df["order_date"].dt.to_period("M").astype(str))["sales"].sum()
    if len(monthly_rev) >= 4:
        q75 = float(monthly_rev.quantile(0.75))
        q25 = float(monthly_rev.quantile(0.25))
        results.append({
            "metric": "Monthly Revenue",
            "org_value": round(float(monthly_rev.mean()), 2),
            "benchmark_low": round(q25, 2),
            "benchmark_high": round(q75, 2),
            "unit": "USD",
        })

    results.append({
        "metric": "Profit Margin",
        "org_value": mgn.get("value", 0),
        "benchmark_low": 8.0,
        "benchmark_high": 20.0,
        "unit": "%",
    })
    results.append({
        "metric": "Repeat Purchase Rate",
        "org_value": rpt.get("value", 0),
        "benchmark_low": 25.0,
        "benchmark_high": 55.0,
        "unit": "%",
    })
    results.append({
        "metric": "Avg Order Value",
        "org_value": aov.get("value", 0),
        "benchmark_low": round(float(df["sales"].quantile(0.25)), 2) if not df.empty else 0,
        "benchmark_high": round(float(df["sales"].quantile(0.75)), 2) if not df.empty else 0,
        "unit": "USD",
    })
    return results


def _generate_action_items(kpis: dict, segmentation: list, top_root_cause: dict, health_score: float) -> list:
    """Rank priority action items from the analysis."""
    actions = []

    # Revenue below baseline
    rev = kpis.get("total_revenue", {})
    if rev and rev.get("baseline", 0) > 0 and rev["value"] < rev["baseline"]:
        gap = rev["baseline"] - rev["value"]
        actions.append({
            "priority": 1,
            "area": "Revenue Recovery",
            "action": f"Revenue is ${gap:,.0f} below baseline. Launch targeted campaigns for lapsed customers.",
            "impact": "High",
            "effort": "Medium",
        })

    # Poor margin
    mgn = kpis.get("profit_margin_pct", {})
    if mgn and mgn.get("value", 100) < 10:
        actions.append({
            "priority": 2,
            "area": "Margin Improvement",
            "action": f"Profit margin at {mgn['value']:.1f}% is critically low. Review discount strategy and product mix.",
            "impact": "High",
            "effort": "Medium",
        })

    # At-Risk customers
    at_risk = next((s for s in segmentation if s["segment"] == "At-Risk"), None)
    if at_risk and at_risk["customer_count"] > 0:
        actions.append({
            "priority": 3,
            "area": "Customer Retention",
            "action": f"Re-engage {at_risk['customer_count']:,} at-risk customers with win-back campaigns (avg spend ${at_risk['avg_spend']:,.0f}).",
            "impact": "High",
            "effort": "Low",
        })

    # Top root cause
    if top_root_cause.get("factor") and top_root_cause.get("confidence", 0) > 0.5:
        actions.append({
            "priority": 4,
            "area": "Root Cause",
            "action": f"Address top causal factor: '{top_root_cause['factor']}' (confidence {top_root_cause['confidence'] * 100:.0f}%). Evidence: {top_root_cause.get('evidence', '')}",
            "impact": "Medium",
            "effort": "High",
        })

    # Low repeat rate
    rpt = kpis.get("repeat_rate_pct", {})
    if rpt and rpt.get("value", 100) < 40:
        actions.append({
            "priority": 5,
            "area": "Loyalty Building",
            "action": f"Repeat purchase rate is {rpt['value']:.0f}%. Implement loyalty program or subscription offering.",
            "impact": "Medium",
            "effort": "Medium",
        })

    # Sort by priority and return top 6
    return sorted(actions, key=lambda x: x["priority"])[:6]


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("/report")
def get_analysis_report():
    """
    Returns the complete deep analysis for the current dataset:
    org identity, health score, KPIs, segmentation, drift series,
    root cause fishbone, 6-month forecast, and priority action items.
    """
    db = SessionLocal()
    try:
        meta = db.query(DatasetMeta).order_by(DatasetMeta.id.desc()).first()
        df   = _get_orders_df(db)

        if df.empty:
            raise HTTPException(status_code=404, detail="No data loaded. Please upload a dataset first.")

        # ── KPIs ──────────────────────────────────────────────────────────────
        kpis = _compute_kpis(df)

        # ── Segmentation ──────────────────────────────────────────────────────
        segmentation = _compute_segmentation(df)

        # ── Drift series ──────────────────────────────────────────────────────
        drift_series = _compute_drift_series(df)

        # ── Anomaly detection + root cause ────────────────────────────────────
        monthly_for_anomaly = pd.DataFrame([
            {"ds": pd.Timestamp(row["month"]), "y": row["revenue"]}
            for row in drift_series
        ])
        anomalies = detect_anomalies(monthly_for_anomaly) if not monthly_for_anomaly.empty else []
        anomaly_months = [a["date"] for a in anomalies]
        fishbone_result = build_fishbone(df, anomaly_months)

        # ── Forecast ──────────────────────────────────────────────────────────
        forecast = _compute_forecast(df, horizon=6)

        # ── Benchmark comparison ───────────────────────────────────────────────
        benchmarks = _compute_benchmarks(kpis, df)

        # ── Health score ──────────────────────────────────────────────────────
        health_score = _compute_health_score(kpis, segmentation, anomalies, df)

        # ── Priority action items ──────────────────────────────────────────────
        action_items = _generate_action_items(kpis, segmentation, fishbone_result.get("top_root_cause", {}), health_score)

        # ── Org identity ──────────────────────────────────────────────────────
        org_info = {
            "org_name":     meta.org_name if meta else None,
            "dataset_name": meta.dataset_name if meta else "Seeded Dataset",
            "uploaded_at":  str(meta.uploaded_at) if meta else None,
            "row_count":    meta.row_count if meta else len(df),
            "customer_count": meta.customer_count if meta else df["customer_id"].nunique(),
            "total_sales":  meta.total_sales if meta else round(float(df["sales"].sum()), 2),
            "date_from":    str(df["order_date"].min().date()) if not df.empty else None,
            "date_to":      str(df["order_date"].max().date()) if not df.empty else None,
        }

        return {
            "org":            org_info,
            "health_score":   health_score,
            "kpis":           kpis,
            "segmentation":   segmentation,
            "drift_series":   drift_series,
            "anomalies":      anomalies,
            "root_cause":     fishbone_result,
            "forecast":       forecast,
            "benchmarks":     benchmarks,
            "action_items":   action_items,
            "generated_at":   datetime.utcnow().isoformat(),
        }
    finally:
        db.close()


@router.get("/health-score")
def get_health_score():
    """Returns a single 0–100 org health score derived from the current dataset."""
    db = SessionLocal()
    try:
        df = _get_orders_df(db)
        if df.empty:
            return {"score": 0, "status": "No Data"}

        kpis         = _compute_kpis(df)
        segmentation = _compute_segmentation(df)
        drift_series = _compute_drift_series(df)
        monthly_for_anomaly = pd.DataFrame([
            {"ds": pd.Timestamp(row["month"]), "y": row["revenue"]}
            for row in drift_series
        ])
        anomalies = detect_anomalies(monthly_for_anomaly) if not monthly_for_anomaly.empty else []
        score     = _compute_health_score(kpis, segmentation, anomalies, df)

        if score >= 75:
            status = "Excellent"
        elif score >= 55:
            status = "Good"
        elif score >= 35:
            status = "Warning"
        else:
            status = "Critical"

        return {"score": score, "status": status}
    finally:
        db.close()
