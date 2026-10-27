"""
Root Cause Analysis API.

Returns the monthly revenue series, statistically flagged anomaly months, and —
for the selected month — a full driver decomposition plus the Ishikawa fishbone.
"""
from datetime import datetime

import pandas as pd
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from db.database import get_db
from ml.root_cause import build_fishbone, detect_anomalies, explain_anomaly, seasonal_baseline
from security import require_user
from services.analytics import load_orders_df, monthly_frame, money
from services.dataset import gate_module
from services.ingestion import active_dataset
from services.modules import build_module

router = APIRouter()


@router.get("")
def get_rootcause(
    month: str | None = Query(None, description="YYYY-MM anomaly month to explain"),
    db: Session = Depends(get_db),
    owner: str = Depends(require_user),
):
    meta = active_dataset(db, owner)
    if meta is not None and meta.schema_kind != "sales":
        return build_module(db, owner, "rootcause")

    blocked = gate_module(db, owner, "rootcause")
    if blocked:
        return blocked

    df = load_orders_df(db, owner, with_customer=True)
    if df.empty:
        return {
            "has_data": False,
            "monthly_series": [],
            "anomalies": [],
            "selected": None,
            "fishbone": {},
            "top_root_cause": None,
            "summary": None,
            "generated_at": datetime.utcnow().isoformat(),
        }

    monthly = monthly_frame(df)
    series_frame = pd.DataFrame(
        {
            "month": monthly["month"],
            "value": monthly["sales"].astype(float),
        }
    )
    anomalies = detect_anomalies(series_frame)

    # Seasonally adjusted expectation for every month, so the chart can show the
    # normal band even in months that were not flagged.
    baseline = seasonal_baseline(series_frame)
    expected = [round(float(value), 2) for value in baseline["expected"]]
    seasonal = [round(float(value), 2) for value in baseline["seasonal_index"]]

    monthly_series = [
        {
            "month": str(row.month),
            "sales": money(row.sales),
            "profit": money(row.profit),
            "orders": int(row.orders),
            "margin": round(float(row.margin), 2),
            "expected": expected[index],
            "seasonal_index": seasonal[index],
        }
        for index, row in enumerate(monthly.itertuples(index=False))
    ]

    # Default to the most damaging drop, else the largest absolute movement.
    drops = [a for a in anomalies if a["type"] == "drop"]
    default_month = min(drops, key=lambda a: a["gap"])["month"] if drops else (
        max(anomalies, key=lambda a: abs(a["gap"]))["month"] if anomalies else None
    )
    selected_month = month or default_month
    if selected_month and selected_month not in {a["month"] for a in anomalies}:
        selected_month = default_month

    selected_anomaly = next((a for a in anomalies if a["month"] == selected_month), None)
    explanation = (
        explain_anomaly(
            df,
            selected_month,
            expected=selected_anomaly["expected"] if selected_anomaly else None,
        )
        if selected_month
        else None
    )
    if explanation is not None:
        explanation["type"] = selected_anomaly["type"] if selected_anomaly else "normal"
        explanation["severity"] = selected_anomaly["severity"] if selected_anomaly else "low"
        explanation["z_score"] = selected_anomaly["z_score"] if selected_anomaly else 0.0
        explanation["expected"] = selected_anomaly["expected"] if selected_anomaly else explanation["revenue"]["baseline"]

    fishbone = build_fishbone(df, explanation)

    drops = [a for a in anomalies if a["type"] == "drop"]
    spikes = [a for a in anomalies if a["type"] == "spike"]
    summary = {
        "months_monitored": int(len(monthly)),
        "anomaly_count": len(anomalies),
        "drops": len(drops),
        "spikes": len(spikes),
        "worst": min(drops, key=lambda a: a["gap"]) if drops else None,
        "largest_swing": round(max((abs(a["gap"]) for a in anomalies), default=0.0), 2),
        "net_swing": round(sum(a["gap"] for a in anomalies), 2),
        "period_from": monthly_series[0]["month"] if monthly_series else None,
        "period_to": monthly_series[-1]["month"] if monthly_series else None,
    }

    return {
        "has_data": True,
        "monthly_series": monthly_series,
        "anomalies": anomalies,
        "selected": explanation,
        "fishbone": fishbone["fishbone"],
        "top_root_cause": fishbone["top_root_cause"],
        "summary": summary,
        "generated_at": datetime.utcnow().isoformat(),
    }
