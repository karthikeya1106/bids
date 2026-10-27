"""
Forecasting API.

``GET /api/forecast`` returns a backtested forecast with confidence bands plus
the context needed to judge it (holdout accuracy, category split, elasticities).
``POST /api/forecast/whatif`` reuses the same base forecast for the simulation so
the two views always agree.
"""
from datetime import datetime
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.database import get_db
from ml.forecaster import forecast_sales, simulate_whatif
from security import require_user
from services.analytics import load_orders_df, monthly_frame
from services.dataset import gate_module
from services.ingestion import active_dataset
from services.modules import build_module
from services.optimizer import optimise_levers

router = APIRouter()


class WhatIfRequest(BaseModel):
    price_change: float = Field(0, ge=-50, le=50)
    discount_change: float = Field(0, ge=-50, le=50)
    marketing_boost: float = Field(0, ge=0, le=200)
    horizon_months: int = Field(6, ge=3, le=12)
    marketing_spend: float = Field(0, ge=0)


class OptimizeRequest(BaseModel):
    horizon_months: int = Field(6, ge=3, le=12)
    marketing_spend: float = Field(0, ge=0)
    max_price_change: float = Field(15, ge=0, le=50)
    max_discount_cut: float = Field(40, ge=0, le=50)
    max_marketing_boost: float = Field(50, ge=0, le=200)
    min_revenue_impact_pct: Optional[float] = Field(None, ge=-100, le=0)
    # Current marketing spend over the horizon. A boost is only charged to profit
    # when this baseline is supplied; otherwise the response says so.
    marketing_spend: float = Field(0, ge=0, le=50_000_000)


def _series(db: Session, owner: str) -> tuple[pd.DataFrame, pd.DataFrame] | tuple[None, None]:
    df = load_orders_df(db, owner, with_customer=True)
    if df.empty:
        return None, None
    monthly = monthly_frame(df)
    series = pd.DataFrame(
        {
            "ds": pd.to_datetime(monthly["month"].astype(str) + "-01"),
            "y": monthly["sales"].astype(float),
        }
    )
    return df, series


@router.get("")
def get_forecast(
    horizon: int = Query(6, ge=3, le=12, description="Months to forecast"),
    db: Session = Depends(get_db),
    owner: str = Depends(require_user),
):
    meta = active_dataset(db, owner)
    if meta is not None and meta.schema_kind != "sales":
        return build_module(db, owner, "forecast")

    blocked = gate_module(db, owner, "forecast")
    if blocked:
        return blocked

    df, series = _series(db, owner)
    if df is None or series is None:
        return {
            "has_data": False,
            "historical": [],
            "forecast": [],
            "model": "No data",
            "generated_at": datetime.utcnow().isoformat(),
        }

    result = forecast_sales(series, horizon_months=horizon, orders_df=df)
    result["generated_at"] = datetime.utcnow().isoformat()
    return result


@router.post("/whatif")
def whatif_simulation(
    body: WhatIfRequest,
    db: Session = Depends(get_db),
    owner: str = Depends(require_user),
):
    meta = active_dataset(db, owner)
    if meta is None or meta.schema_kind != "sales":
        raise HTTPException(
            status_code=400,
            detail="What-if simulation is defined on sales revenue. This dataset does not have a sales timeline.",
        )
    blocked = gate_module(db, owner, "forecast")
    if blocked:
        return blocked

    df, series = _series(db, owner)
    if df is None or series is None:
        return {"error": "No data available"}

    base = forecast_sales(series, horizon_months=body.horizon_months, orders_df=df)
    return simulate_whatif(
        series,
        body.price_change,
        body.discount_change,
        body.marketing_boost,
        horizon_months=body.horizon_months,
        base=base,
        marketing_spend=body.marketing_spend,
    )


@router.post("/optimize")
def optimize_levers(
    body: OptimizeRequest,
    db: Session = Depends(get_db),
    owner: str = Depends(require_user),
):
    """Search the simulator's lever space and recommend a combination.

    Unlike ``/whatif`` this returns a recommendation rather than a score for
    levers the user typed in. Both use the same base forecast and simulator, so
    a recommended plan can be reproduced by hand in the simulator.
    """
    meta = active_dataset(db, owner)
    if meta is None or meta.schema_kind != "sales":
        raise HTTPException(
            status_code=400,
            detail="Lever optimisation is defined on sales revenue. This dataset does not have a sales timeline.",
        )
    blocked = gate_module(db, owner, "forecast")
    if blocked:
        return blocked

    df, series = _series(db, owner)
    if df is None or series is None:
        return {"has_data": False, "error": "No data available"}

    base = forecast_sales(series, horizon_months=body.horizon_months, orders_df=df)
    return optimise_levers(
        series,
        horizon_months=body.horizon_months,
        marketing_spend=body.marketing_spend,
        base=base,
        max_price_change=body.max_price_change,
        max_discount_cut=body.max_discount_cut,
        max_marketing_boost=body.max_marketing_boost,
        min_revenue_impact_pct=body.min_revenue_impact_pct,
    )
