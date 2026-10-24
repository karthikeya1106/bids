"""
Forecasting API.

``GET /api/forecast`` returns a backtested forecast with confidence bands plus
the context needed to judge it (holdout accuracy, category split, elasticities).
``POST /api/forecast/whatif`` reuses the same base forecast for the simulation so
the two views always agree.
"""
from datetime import datetime

import pandas as pd
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.database import get_db
from ml.forecaster import forecast_sales, simulate_whatif
from security import require_user
from services.analytics import load_orders_df, monthly_frame

router = APIRouter()


class WhatIfRequest(BaseModel):
    price_change: float = Field(0, ge=-50, le=50)
    discount_change: float = Field(0, ge=-50, le=50)
    marketing_boost: float = Field(0, ge=0, le=200)
    horizon_months: int = Field(6, ge=3, le=12)


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
    )
