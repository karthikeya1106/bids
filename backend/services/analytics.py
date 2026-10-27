"""
Shared analytics helpers used by the dashboard, behavior and segmentation APIs.

Everything here is computed from the ``orders`` / ``customers`` tables — there are
no hardcoded metrics, so every number a page shows is derived from the dataset
that is actually loaded.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from db.models import Customer, KPI, Order
from ml.drift_detector import detect_drift_adwin

# Canonical order frame columns. Keeping this explicit means downstream code can
# rely on the schema even when the dataset is empty.
ORDER_COLUMNS = [
    "order_id", "order_date", "ship_date", "customer_id", "category",
    "sub_category", "product_name", "sales", "quantity", "discount", "profit",
    "ship_lag_days",
]


def load_orders_df(db: Session, owner_id: str, with_customer: bool = False) -> pd.DataFrame:
    """Load one workspace's orders into a typed DataFrame.

    ``owner_id`` is always supplied from the verified request identity, never
    from the client, so a workspace can only ever read its own rows.
    """
    orders = db.query(Order).filter(Order.owner_id == owner_id).all()
    if not orders:
        return pd.DataFrame(columns=ORDER_COLUMNS)

    df = pd.DataFrame(
        {
            "order_id": [o.order_id for o in orders],
            "order_date": [o.order_date for o in orders],
            "ship_date": [o.ship_date for o in orders],
            "customer_id": [o.customer_id for o in orders],
            "category": [o.category for o in orders],
            "sub_category": [o.sub_category for o in orders],
            "product_name": [o.product_name for o in orders],
            "sales": [o.sales if o.sales is not None else 0.0 for o in orders],
            "quantity": [o.quantity if o.quantity is not None else 0 for o in orders],
            "discount": [o.discount if o.discount is not None else 0.0 for o in orders],
            "profit": [o.profit if o.profit is not None else 0.0 for o in orders],
        }
    )

    df["order_date"] = pd.to_datetime(df["order_date"], errors="coerce")
    df["ship_date"] = pd.to_datetime(df["ship_date"], errors="coerce")
    df = df.dropna(subset=["order_date"])

    df["ship_lag_days"] = (df["ship_date"] - df["order_date"]).dt.days.astype("float")
    for col in ["sales", "quantity", "discount", "profit"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    if with_customer:
        customers = db.query(Customer).filter(Customer.owner_id == owner_id).all()
        if customers:
            cdf = pd.DataFrame(
                [
                    {
                        "customer_id": c.customer_id,
                        "customer_name": c.customer_name,
                        "customer_segment": c.segment,
                        "region": c.region,
                        "state": c.state,
                        "city": c.city,
                    }
                    for c in customers
                ]
            )
            df = df.merge(cdf, on="customer_id", how="left")
        else:
            df["customer_name"] = df["customer_id"]
            df["customer_segment"] = "Unknown"
            df["region"] = "Unknown"
            df["state"] = "Unknown"
            df["city"] = "Unknown"

    return df


def monthly_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate orders into one row per calendar month."""
    if df.empty:
        return pd.DataFrame(
            columns=["month", "sales", "profit", "orders", "customers", "quantity", "margin", "aov"]
        )

    work = df.copy()
    work["month"] = work["order_date"].dt.to_period("M")
    monthly = (
        work.groupby("month")
        .agg(
            sales=("sales", "sum"),
            profit=("profit", "sum"),
            orders=("order_id", "nunique"),
            customers=("customer_id", "nunique"),
            quantity=("quantity", "sum"),
        )
        .reset_index()
        .sort_values("month")
    )
    monthly["margin"] = np.where(
        monthly["sales"] != 0, monthly["profit"] / monthly["sales"] * 100, 0.0
    )
    monthly["aov"] = np.where(monthly["orders"] != 0, monthly["sales"] / monthly["orders"], 0.0)
    monthly["month"] = monthly["month"].astype(str)
    return monthly


def money(value: float) -> float:
    return round(float(value), 2)


def pct_delta(current: float, previous: float) -> Optional[float]:
    """Percentage change, or None when there is no meaningful baseline."""
    if previous is None or previous == 0 or pd.isna(previous):
        return None
    return round((current - previous) / abs(previous) * 100, 1)


def period_stats(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    """Headline metrics for an arbitrary date window (end exclusive)."""
    window = df[(df["order_date"] >= start) & (df["order_date"] < end)]
    orders = int(window["order_id"].nunique())
    customers = int(window["customer_id"].nunique())
    sales = float(window["sales"].sum())
    profit = float(window["profit"].sum())
    return {
        "orders": orders,
        "customers": customers,
        "sales": sales,
        "profit": profit,
        "margin": round(profit / sales * 100, 2) if sales else 0.0,
        "aov": round(sales / orders, 2) if orders else 0.0,
    }


def repeat_purchase_rate(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> float:
    """Share of customers with 2+ orders inside the window (end exclusive)."""
    window = df[(df["order_date"] >= start) & (df["order_date"] < end)]
    if window.empty:
        return 0.0
    counts = window.groupby("customer_id")["order_id"].nunique()
    if len(counts) == 0:
        return 0.0
    return round(float((counts > 1).sum()) / len(counts) * 100, 1)


def retention_snapshot(df: pd.DataFrame, anchor: pd.Timestamp, window_days: int = 90) -> dict:
    """
    Retention / churn / acquisition over the trailing window, anchored at the
    latest order in the dataset (not at "today", so historic datasets still work).
    """
    current_start = anchor - pd.Timedelta(days=window_days)
    previous_start = anchor - pd.Timedelta(days=window_days * 2)

    current = df[df["order_date"] > current_start]
    previous = df[(df["order_date"] > previous_start) & (df["order_date"] <= current_start)]

    active_now = set(current["customer_id"].unique())
    active_before = set(previous["customer_id"].unique())

    retained = active_now & active_before
    retention_rate = round(len(retained) / len(active_before) * 100, 1) if active_before else 0.0
    churn_rate = round(100 - retention_rate, 1) if active_before else 0.0

    first_order = df.groupby("customer_id")["order_date"].min()
    new_customers = int((first_order > current_start).sum())
    new_customers_previous = int(
        ((first_order > previous_start) & (first_order <= current_start)).sum()
    )

    return {
        "retention_rate": retention_rate,
        "churn_rate": churn_rate,
        "new_customers": new_customers,
        "new_customers_previous": new_customers_previous,
        "active_now": len(active_now),
        "active_previous": len(active_before),
        "retained": len(retained),
    }


def _kpi_targets(current: float, baseline: float, kind: str) -> float:
    """Targets are expressed relative to the previous period."""
    if kind == "percent":
        return round(current * 1.10, 2)
    if kind == "inverse_percent":
        return round(current * 0.90, 2)
    return round((baseline or current) * 1.10, 2)


def recalculate_kpis(db: Session, owner_id: str) -> None:
    """
    Recompute the KPI table from the loaded orders so the drift page, dashboard
    alerts and strategy prompt all agree with each other.

    Current = trailing 90 days, baseline = the 90 days before that, drift is
    measured with ADWIN over the monthly series rather than being hardcoded.
    """
    df = load_orders_df(db, owner_id)
    if df.empty:
        return

    anchor = df["order_date"].max() + pd.Timedelta(days=1)
    window = 90
    current = period_stats(df, anchor - pd.Timedelta(days=window), anchor)
    previous = period_stats(
        df, anchor - pd.Timedelta(days=window * 2), anchor - pd.Timedelta(days=window)
    )
    retention = retention_snapshot(df, anchor, window)
    # The window before that, so retention / churn have a real baseline rather
    # than being compared with themselves.
    retention_previous = retention_snapshot(df, anchor - pd.Timedelta(days=window), window)

    monthly = monthly_frame(df)
    drift_scores: dict[str, float] = {}
    for column, name in [
        ("sales", "Total Revenue"),
        ("profit", "Profit"),
        ("orders", "Orders"),
        ("aov", "Avg Order Value"),
        ("margin", "Profit Margin"),
    ]:
        series = monthly[column].astype(float).tolist()
        drift_scores[name] = detect_drift_adwin(series)["drift_score"] if len(series) >= 3 else 0.0

    repeat_now = repeat_purchase_rate(
        df, anchor - pd.Timedelta(days=window), anchor
    )
    repeat_before = repeat_purchase_rate(
        df, anchor - pd.Timedelta(days=window * 2), anchor - pd.Timedelta(days=window)
    )

    definitions = [
        {
            "kpi_name": "Total Revenue",
            "current_value": money(current["sales"]),
            "baseline_value": money(previous["sales"]),
            "target_value": _kpi_targets(current["sales"], previous["sales"], "currency"),
            "drift_score": drift_scores.get("Total Revenue", 0.0),
            "unit": "USD",
        },
        {
            "kpi_name": "Avg Order Value",
            "current_value": money(current["aov"]),
            "baseline_value": money(previous["aov"]),
            "target_value": _kpi_targets(current["aov"], previous["aov"], "currency"),
            "drift_score": drift_scores.get("Avg Order Value", 0.0),
            "unit": "USD",
        },
        {
            "kpi_name": "Profit Margin",
            "current_value": money(current["margin"]),
            "baseline_value": money(previous["margin"]),
            "target_value": _kpi_targets(current["margin"], previous["margin"], "percent"),
            "drift_score": drift_scores.get("Profit Margin", 0.0),
            "unit": "%",
        },
        {
            "kpi_name": "Repeat Purchase Rate",
            "current_value": repeat_now,
            "baseline_value": repeat_before,
            "target_value": round(min(repeat_now * 1.15, 100), 1),
            "drift_score": drift_scores.get("Orders", 0.0),
            "unit": "%",
        },
        {
            "kpi_name": "Customer Retention Rate",
            "current_value": retention["retention_rate"],
            "baseline_value": retention_previous["retention_rate"],
            "target_value": round(min(retention["retention_rate"] * 1.10, 100), 1),
            "drift_score": drift_scores.get("Profit", 0.0),
            "unit": "%",
        },
        {
            "kpi_name": "Churn Rate",
            "current_value": retention["churn_rate"],
            "baseline_value": retention_previous["churn_rate"],
            "target_value": round(retention["churn_rate"] * 0.85, 1),
            "drift_score": drift_scores.get("Profit Margin", 0.0),
            "unit": "%",
        },
        {
            "kpi_name": "New Customer Acquisition",
            "current_value": retention["new_customers"],
            "baseline_value": retention["new_customers_previous"],
            "target_value": round(max(retention["new_customers"], 1) * 1.10),
            "drift_score": drift_scores.get("Orders", 0.0),
            "unit": "count",
        },
    ]

    now = datetime.utcnow()
    for definition in definitions:
        row = (
            db.query(KPI)
            .filter(KPI.owner_id == owner_id, KPI.kpi_name == definition["kpi_name"])
            .first()
        )
        if row is None:
            db.add(KPI(**definition, owner_id=owner_id, last_updated=now))
        else:
            for key, value in definition.items():
                setattr(row, key, value)
            row.last_updated = now
    db.commit()
