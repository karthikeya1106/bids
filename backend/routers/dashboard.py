"""
Executive dashboard API.

Every figure is derived from the orders actually loaded in the database, with a
trailing-90-day "current" period compared against the preceding 90 days. When
no dataset is loaded the endpoint returns ``has_data: false`` instead of
inventing numbers.
"""
from datetime import datetime

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import DatasetMeta, KPI
from security import require_user
from services.analytics import (
    load_orders_df,
    monthly_frame,
    money,
    pct_delta,
    period_stats,
)

router = APIRouter()

WINDOW_DAYS = 90


def _percent(part: float, total: float) -> float:
    return round(part / total * 100, 2) if total else 0.0


def _dataset_meta(db: Session, df: pd.DataFrame, owner_id: str) -> dict:
    meta = db.query(DatasetMeta).filter(DatasetMeta.owner_id == owner_id).first()
    return {
        "dataset_name": meta.dataset_name if meta else "Seeded dataset",
        "org_name": meta.org_name if meta else None,
        "source": meta.source if meta else "seed",
        "uploaded_at": str(meta.uploaded_at) if meta and meta.uploaded_at else None,
        "rows": int(len(df)),
        "customers": int(df["customer_id"].nunique()),
        "orders": int(df["order_id"].nunique()),
        "date_from": str(df["order_date"].min().date()),
        "date_to": str(df["order_date"].max().date()),
    }


def _window_kpis(current: dict, previous: dict, monthly: pd.DataFrame) -> list[dict]:
    spark = monthly.tail(12)

    def points(column: str) -> list[dict]:
        return [
            {"month": row["month"], "value": round(float(row[column]), 2)}
            for _, row in spark.iterrows()
        ]

    return [
        {
            "key": "revenue",
            "label": "Total Revenue",
            "value": money(current["sales"]),
            "previous": money(previous["sales"]),
            "delta_pct": pct_delta(current["sales"], previous["sales"]),
            "unit": "USD",
            "format": "currency",
            "spark": points("sales"),
        },
        {
            "key": "profit",
            "label": "Net Profit",
            "value": money(current["profit"]),
            "previous": money(previous["profit"]),
            "delta_pct": pct_delta(current["profit"], previous["profit"]),
            "unit": "USD",
            "format": "currency",
            "spark": points("profit"),
        },
        {
            "key": "orders",
            "label": "Orders",
            "value": current["orders"],
            "previous": previous["orders"],
            "delta_pct": pct_delta(current["orders"], previous["orders"]),
            "unit": "count",
            "format": "number",
            "spark": points("orders"),
        },
        {
            "key": "customers",
            "label": "Active Customers",
            "value": current["customers"],
            "previous": previous["customers"],
            "delta_pct": pct_delta(current["customers"], previous["customers"]),
            "unit": "count",
            "format": "number",
            "spark": points("customers"),
        },
        {
            "key": "aov",
            "label": "Avg Order Value",
            "value": money(current["aov"]),
            "previous": money(previous["aov"]),
            "delta_pct": pct_delta(current["aov"], previous["aov"]),
            "unit": "USD",
            "format": "currency",
            "spark": points("aov"),
        },
        {
            "key": "margin",
            "label": "Profit Margin",
            "value": money(current["margin"]),
            "previous": money(previous["margin"]),
            "delta_pct": pct_delta(current["margin"], previous["margin"]),
            "unit": "%",
            "format": "percent",
            "spark": points("margin"),
        },
    ]


def _category_breakdown(df: pd.DataFrame) -> list[dict]:
    grouped = (
        df.groupby("category")
        .agg(sales=("sales", "sum"), profit=("profit", "sum"), orders=("order_id", "nunique"))
        .reset_index()
        .sort_values("sales", ascending=False)
    )
    total_sales = float(grouped["sales"].sum())
    return [
        {
            "category": row["category"] or "Uncategorised",
            "sales": money(row["sales"]),
            "profit": money(row["profit"]),
            "orders": int(row["orders"]),
            "margin": round(row["profit"] / row["sales"] * 100, 2) if row["sales"] else 0.0,
            "share": _percent(row["sales"], total_sales),
        }
        for _, row in grouped.iterrows()
    ]


def _subcategory_performance(df: pd.DataFrame) -> list[dict]:
    grouped = (
        df.groupby("sub_category")
        .agg(sales=("sales", "sum"), profit=("profit", "sum"), orders=("order_id", "nunique"))
        .reset_index()
        .sort_values("sales", ascending=False)
        .head(10)
    )
    return [
        {
            "name": row["sub_category"] or "Uncategorised",
            "sales": money(row["sales"]),
            "profit": money(row["profit"]),
            "orders": int(row["orders"]),
            "margin": round(row["profit"] / row["sales"] * 100, 2) if row["sales"] else 0.0,
        }
        for _, row in grouped.iterrows()
    ]


def _region_breakdown(df: pd.DataFrame) -> list[dict]:
    if "region" not in df.columns:
        return []
    grouped = (
        df.groupby("region")
        .agg(sales=("sales", "sum"), profit=("profit", "sum"), orders=("order_id", "nunique"))
        .reset_index()
        .sort_values("sales", ascending=False)
    )
    total = float(grouped["sales"].sum())
    return [
        {
            "region": row["region"] or "Unknown",
            "sales": money(row["sales"]),
            "profit": money(row["profit"]),
            "orders": int(row["orders"]),
            "share": _percent(row["sales"], total),
        }
        for _, row in grouped.iterrows()
    ]


def _build_alerts(
    db: Session, df: pd.DataFrame, monthly: pd.DataFrame, meta: dict, owner_id: str
) -> list[dict]:
    alerts: list[dict] = []

    # Losing product lines.
    by_category = _category_breakdown(df)
    losers = [c for c in by_category if c["profit"] < 0]
    if losers:
        worst = min(losers, key=lambda c: c["profit"])
        alerts.append(
            {
                "type": "profit",
                "severity": "danger",
                "title": f"{worst['category']} is loss-making",
                "message": (
                    f"{worst['category']} revenue is ${worst['sales']:,.0f} but profit is "
                    f"${worst['profit']:,.0f} ({worst['margin']:.1f}% margin). "
                    f"{len(losers)} categor{'y is' if len(losers) == 1 else 'ies are'} unprofitable."
                ),
            }
        )

    # Overall margin pressure.
    total_sales = float(df["sales"].sum())
    total_profit = float(df["profit"].sum())
    overall_margin = total_profit / total_sales * 100 if total_sales else 0.0
    if overall_margin < 10:
        alerts.append(
            {
                "type": "margin",
                "severity": "warning",
                "title": "Thin overall margin",
                "message": f"Portfolio profit margin is {overall_margin:.1f}%, below the 10% healthy threshold.",
            }
        )

    # Recent momentum.
    if len(monthly) >= 2:
        last, prior = monthly.iloc[-1], monthly.iloc[-2]
        change = pct_delta(last["sales"], prior["sales"])
        if change is not None and change <= -10:
            alerts.append(
                {
                    "type": "momentum",
                    "severity": "warning",
                    "title": f"Revenue down {abs(change):.1f}% month over month",
                    "message": f"{last['month']} closed at ${last['sales']:,.0f} versus ${prior['sales']:,.0f} in {prior['month']}.",
                }
            )

    # Real drift signals stored by the KPI sync.
    drifting = (
        db.query(KPI)
        .filter(KPI.owner_id == owner_id, KPI.drift_score >= 0.3)
        .all()
    )
    for kpi in drifting[:2]:
        alerts.append(
            {
                "type": "drift",
                "severity": "warning",
                "title": f"Drift detected in {kpi.kpi_name}",
                "message": (
                    f"ADWIN flagged a distribution shift (score {kpi.drift_score:.2f}). "
                    f"Current {kpi.current_value:,.2f} {kpi.unit} versus baseline {kpi.baseline_value:,.2f}."
                ),
            }
        )

    # Revenue concentration.
    by_customer = df.groupby("customer_id")["sales"].sum().sort_values(ascending=False)
    if len(by_customer) >= 10 and by_customer.sum() > 0:
        top_ten_share = float(by_customer.head(10).sum() / by_customer.sum() * 100)
        if top_ten_share >= 25:
            alerts.append(
                {
                    "type": "concentration",
                    "severity": "info",
                    "title": "Revenue concentration risk",
                    "message": f"Top 10 customers generate {top_ten_share:.1f}% of revenue across {len(by_customer):,} customers.",
                }
            )

    order = {"danger": 0, "warning": 1, "info": 2}
    return sorted(alerts, key=lambda a: order.get(a["severity"], 3))[:5]


@router.get("")
def get_dashboard(
    months: int = Query(12, ge=3, le=48, description="Months of trend history to return"),
    db: Session = Depends(get_db),
    owner: str = Depends(require_user),
):
    df = load_orders_df(db, owner, with_customer=True)
    if df.empty:
        return {
            "has_data": False,
            "meta": None,
            "period": None,
            "kpis": [],
            "revenue_trend": [],
            "category_breakdown": [],
            "subcategory_performance": [],
            "region_breakdown": [],
            "alerts": [],
            "generated_at": datetime.utcnow().isoformat(),
        }

    meta = _dataset_meta(db, df, owner)
    monthly = monthly_frame(df)

    anchor = df["order_date"].max() + pd.Timedelta(days=1)
    current = period_stats(df, anchor - pd.Timedelta(days=WINDOW_DAYS), anchor)
    previous = period_stats(
        df, anchor - pd.Timedelta(days=WINDOW_DAYS * 2), anchor - pd.Timedelta(days=WINDOW_DAYS)
    )

    trend = monthly.tail(months)
    revenue_trend = [
        {
            "month": row["month"],
            "sales": money(row["sales"]),
            "profit": money(row["profit"]),
            "orders": int(row["orders"]),
            "margin": round(float(row["margin"]), 2),
            "aov": round(float(row["aov"]), 2),
        }
        for _, row in trend.iterrows()
    ]

    return {
        "has_data": True,
        "meta": meta,
        "period": {
            "days": WINDOW_DAYS,
            "current_from": str((anchor - pd.Timedelta(days=WINDOW_DAYS)).date()),
            "current_to": str((anchor - pd.Timedelta(days=1)).date()),
            "previous_from": str((anchor - pd.Timedelta(days=WINDOW_DAYS * 2)).date()),
            "previous_to": str((anchor - pd.Timedelta(days=WINDOW_DAYS + 1)).date()),
        },
        "kpis": _window_kpis(current, previous, monthly),
        "revenue_trend": revenue_trend,
        "category_breakdown": _category_breakdown(df),
        "subcategory_performance": _subcategory_performance(df),
        "region_breakdown": _region_breakdown(df),
        "alerts": _build_alerts(db, df, monthly, meta, owner),
        "generated_at": datetime.utcnow().isoformat(),
    }
