"""
Customer behavior analytics.

Purchase cadence, cohort retention, lifecycle funnel, discount behaviour and
category/region preferences — all computed from the loaded order history.
"""
from datetime import datetime

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.database import get_db
from security import require_user
from services.analytics import load_orders_df, money, retention_snapshot

router = APIRouter()

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _empty_response() -> dict:
    return {
        "has_data": False,
        "summary": {},
        "heatmap": {"x": MONTHS, "y": WEEKDAYS, "z": [], "metric": "Revenue (USD)"},
        "weekday_split": [],
        "funnel": [],
        "cohorts": {"periods": list(range(12)), "rows": []},
        "frequency_distribution": [],
        "discount_bands": [],
        "segment_behavior": [],
        "top_products": [],
        "top_subcategories": [],
        "region_behavior": [],
        "generated_at": datetime.utcnow().isoformat(),
    }


def _summary(df: pd.DataFrame) -> dict:
    orders_per_customer = df.groupby("customer_id")["order_id"].nunique()
    customers = int(len(orders_per_customer))
    orders = int(df["order_id"].nunique())
    revenue = float(df["sales"].sum())

    repeat = int((orders_per_customer >= 2).sum())
    loyal = int((orders_per_customer >= 3).sum())
    champions = int((orders_per_customer >= 5).sum())

    # Average gap between a customer's consecutive orders.
    dated = (
        df[["customer_id", "order_id", "order_date"]]
        .drop_duplicates(["customer_id", "order_id"])
        .sort_values(["customer_id", "order_date"])
    )
    gaps = dated.groupby("customer_id")["order_date"].diff().dt.days.dropna()
    avg_gap = round(float(gaps.mean()), 1) if len(gaps) else None

    anchor = df["order_date"].max() + pd.Timedelta(days=1)
    retention = retention_snapshot(df, anchor, 90)

    weekend = df[df["order_date"].dt.dayofweek >= 5]["sales"].sum()
    lag = df["ship_lag_days"].dropna()

    return {
        "customers": customers,
        "orders": orders,
        "revenue": money(revenue),
        "repeat_customers": repeat,
        "loyal_customers": loyal,
        "champion_customers": champions,
        "repeat_rate": round(repeat / customers * 100, 1) if customers else 0.0,
        "loyal_rate": round(loyal / customers * 100, 1) if customers else 0.0,
        "retention_rate": retention["retention_rate"],
        "churn_rate": retention["churn_rate"],
        "new_customers_90d": retention["new_customers"],
        "retained_customers_90d": retention["retained"],
        "avg_orders_per_customer": round(float(orders_per_customer.mean()), 2) if customers else 0.0,
        "avg_days_between_orders": avg_gap,
        "avg_basket_value": round(revenue / orders, 2) if orders else 0.0,
        "avg_items_per_order": round(float(df["quantity"].sum()) / orders, 2) if orders else 0.0,
        "avg_ship_lag_days": round(float(lag.mean()), 1) if len(lag) else None,
        "weekend_share": round(float(weekend) / revenue * 100, 1) if revenue else 0.0,
        "avg_discount": round(float(df["discount"].mean()) * 100, 2),
    }


def _heatmap(df: pd.DataFrame) -> dict:
    work = df.copy()
    work["weekday"] = work["order_date"].dt.dayofweek
    work["month"] = work["order_date"].dt.month
    pivot = (
        work.pivot_table(
            index="weekday", columns="month", values="sales", aggfunc="sum", fill_value=0.0
        )
        .reindex(index=range(7), columns=range(1, 13), fill_value=0.0)
    )
    return {
        "x": MONTHS,
        "y": WEEKDAYS,
        "z": [[round(float(pivot.loc[d, m]), 2) for m in range(1, 13)] for d in range(7)],
        "metric": "Revenue (USD)",
    }


def _weekday_split(df: pd.DataFrame) -> list[dict]:
    work = df.copy()
    work["weekday"] = work["order_date"].dt.dayofweek
    grouped = (
        work.groupby("weekday")
        .agg(sales=("sales", "sum"), orders=("order_id", "nunique"))
        .reindex(range(7), fill_value=0)
    )
    total = float(grouped["sales"].sum())
    return [
        {
            "day": WEEKDAYS[idx],
            "sales": money(row["sales"]),
            "orders": int(row["orders"]),
            "share": round(float(row["sales"]) / total * 100, 1) if total else 0.0,
            "weekend": idx >= 5,
        }
        for idx, row in grouped.iterrows()
    ]


def _funnel(df: pd.DataFrame) -> list[dict]:
    counts = df.groupby("customer_id")["order_id"].nunique()
    total = int(len(counts))
    stages = [
        ("Active Customers", total),
        ("Repeat Buyers (2+)", int((counts >= 2).sum())),
        ("Loyal Customers (3+)", int((counts >= 3).sum())),
        ("Champions (5+)", int((counts >= 5).sum())),
    ]
    funnel = []
    for idx, (stage, value) in enumerate(stages):
        previous = stages[idx - 1][1] if idx else value
        funnel.append(
            {
                "stage": stage,
                "value": value,
                "pct_of_total": round(value / total * 100, 1) if total else 0.0,
                "conversion": round(value / previous * 100, 1) if previous else 0.0,
            }
        )
    return funnel


def _cohorts(df: pd.DataFrame, horizon: int = 10) -> dict:
    """Quarterly acquisition cohorts and their retention by quarter offset."""
    work = df[["customer_id", "order_date"]].copy()
    work["order_quarter"] = work["order_date"].dt.to_period("Q")
    first_quarter = work.groupby("customer_id")["order_quarter"].min().rename("cohort")
    work = work.join(first_quarter, on="customer_id")
    work["offset"] = (work["order_quarter"] - work["cohort"]).apply(lambda p: p.n)

    active = (
        work.groupby(["cohort", "offset"])["customer_id"].nunique().unstack(fill_value=0)
    )
    sizes = work.groupby("cohort")["customer_id"].nunique()

    cohorts = list(active.index)[-horizon:]
    last_quarter = work["order_quarter"].max()
    periods = list(range(horizon))

    rows = []
    for cohort in cohorts:
        size = int(sizes.loc[cohort])
        observed = (last_quarter - cohort).n  # quarters of history available
        values = []
        for offset in periods:
            if offset > observed:
                values.append(None)  # not enough history yet
                continue
            retained = int(active.loc[cohort].get(offset, 0)) if offset in active.columns else 0
            values.append(round(retained / size * 100, 1) if size else 0.0)
        rows.append(
            {
                "cohort": f"{cohort.year} Q{cohort.quarter}",
                "size": size,
                "values": values,
            }
        )

    return {"periods": periods, "rows": rows}


def _frequency_distribution(df: pd.DataFrame) -> list[dict]:
    counts = df.groupby("customer_id")["order_id"].nunique()
    total = int(len(counts))
    buckets = [
        ("1 order", int((counts == 1).sum())),
        ("2 orders", int((counts == 2).sum())),
        ("3 orders", int((counts == 3).sum())),
        ("4 orders", int((counts == 4).sum())),
        ("5-9 orders", int(((counts >= 5) & (counts <= 9)).sum())),
        ("10+ orders", int((counts >= 10).sum())),
    ]
    return [
        {"bucket": label, "customers": value, "share": round(value / total * 100, 1) if total else 0.0}
        for label, value in buckets
    ]


def _discount_bands(df: pd.DataFrame) -> list[dict]:
    if "discount" not in df.columns:
        return []
    work = df.copy()
    bands = [
        ("0%", -0.001, 0.0001),
        ("1-10%", 0.0001, 0.1001),
        ("11-20%", 0.1001, 0.2001),
        ("21-30%", 0.2001, 0.3001),
        ("31%+", 0.3001, 1.01),
    ]
    total_revenue = float(work["sales"].sum())
    result = []
    for label, lower, upper in bands:
        subset = work[(work["discount"] >= lower) & (work["discount"] < upper)]
        sales = float(subset["sales"].sum())
        profit = float(subset["profit"].sum())
        result.append(
            {
                "band": label,
                "orders": int(subset["order_id"].nunique()),
                "sales": money(sales),
                "profit": money(profit),
                "margin": round(profit / sales * 100, 1) if sales else 0.0,
                "share": round(sales / total_revenue * 100, 1) if total_revenue else 0.0,
            }
        )
    return result


def _segment_behavior(df: pd.DataFrame) -> list[dict]:
    if "customer_segment" not in df.columns:
        return []
    work = df.copy()
    work["customer_segment"] = work["customer_segment"].fillna("Unknown")
    total_revenue = float(work["sales"].sum())

    orders_per_customer = work.groupby("customer_id")["order_id"].nunique()
    customers_by_segment = (
        work.drop_duplicates("customer_id").groupby("customer_segment")["customer_id"].count()
    )

    grouped = (
        work.groupby("customer_segment")
        .agg(sales=("sales", "sum"), profit=("profit", "sum"), orders=("order_id", "nunique"))
        .reset_index()
        .sort_values("sales", ascending=False)
    )

    result = []
    for _, row in grouped.iterrows():
        segment = row["customer_segment"]
        customers = int(customers_by_segment.get(segment, 0))
        segment_customers = work[work["customer_segment"] == segment]["customer_id"].unique()
        avg_orders = float(orders_per_customer.loc[segment_customers].mean()) if customers else 0.0
        result.append(
            {
                "segment": segment,
                "customers": customers,
                "orders": int(row["orders"]),
                "revenue": money(row["sales"]),
                "profit": money(row["profit"]),
                "revenue_share": round(row["sales"] / total_revenue * 100, 1) if total_revenue else 0.0,
                "avg_order_value": round(row["sales"] / row["orders"], 2) if row["orders"] else 0.0,
                "avg_orders_per_customer": round(avg_orders, 2),
                "margin": round(row["profit"] / row["sales"] * 100, 1) if row["sales"] else 0.0,
            }
        )
    return result


def _top_products(df: pd.DataFrame, limit: int = 8) -> list[dict]:
    grouped = (
        df.groupby("product_name")
        .agg(sales=("sales", "sum"), profit=("profit", "sum"), orders=("order_id", "nunique"))
        .reset_index()
        .sort_values("sales", ascending=False)
        .head(limit)
    )
    return [
        {
            "name": row["product_name"],
            "sales": money(row["sales"]),
            "profit": money(row["profit"]),
            "orders": int(row["orders"]),
        }
        for _, row in grouped.iterrows()
    ]


def _top_subcategories(df: pd.DataFrame, limit: int = 8) -> list[dict]:
    grouped = (
        df.groupby("sub_category")
        .agg(sales=("sales", "sum"), profit=("profit", "sum"), orders=("order_id", "nunique"))
        .reset_index()
        .sort_values("sales", ascending=False)
        .head(limit)
    )
    return [
        {
            "name": row["sub_category"],
            "sales": money(row["sales"]),
            "profit": money(row["profit"]),
            "orders": int(row["orders"]),
        }
        for _, row in grouped.iterrows()
    ]


def _region_behavior(df: pd.DataFrame) -> list[dict]:
    if "region" not in df.columns:
        return []
    grouped = (
        df.groupby("region")
        .agg(sales=("sales", "sum"), orders=("order_id", "nunique"), customers=("customer_id", "nunique"))
        .reset_index()
        .sort_values("sales", ascending=False)
    )
    total = float(grouped["sales"].sum())
    return [
        {
            "region": row["region"] or "Unknown",
            "revenue": money(row["sales"]),
            "orders": int(row["orders"]),
            "customers": int(row["customers"]),
            "share": round(row["sales"] / total * 100, 1) if total else 0.0,
        }
        for _, row in grouped.iterrows()
    ]


@router.get("")
def get_behavior(db: Session = Depends(get_db), owner: str = Depends(require_user)):
    df = load_orders_df(db, owner, with_customer=True)
    if df.empty:
        return _empty_response()

    return {
        "has_data": True,
        "summary": _summary(df),
        "heatmap": _heatmap(df),
        "weekday_split": _weekday_split(df),
        "funnel": _funnel(df),
        "cohorts": _cohorts(df),
        "frequency_distribution": _frequency_distribution(df),
        "discount_bands": _discount_bands(df),
        "segment_behavior": _segment_behavior(df),
        "top_products": _top_products(df),
        "top_subcategories": _top_subcategories(df),
        "region_behavior": _region_behavior(df),
        "generated_at": datetime.utcnow().isoformat(),
    }
