from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from db.database import get_db
from db.models import Order
from ml.forecaster import forecast_sales, simulate_whatif
import pandas as pd

router = APIRouter()


class WhatIfRequest(BaseModel):
    price_change: float = 0       # % change in price
    discount_change: float = 0    # % change in discount
    marketing_boost: float = 0    # % increase in marketing spend


@router.get("")
def get_forecast(db: Session = Depends(get_db)):
    orders = db.query(Order).all()
    if not orders:
        return {"historical": [], "forecast": [], "model": "No data"}

    df = pd.DataFrame([{"order_date": pd.to_datetime(o.order_date), "sales": o.sales} for o in orders])
    df["month"] = df["order_date"].dt.to_period("M")
    monthly = df.groupby("month")["sales"].sum().reset_index()
    monthly["ds"] = monthly["month"].dt.to_timestamp()
    monthly.rename(columns={"sales": "y"}, inplace=True)
    monthly = monthly.sort_values("ds").reset_index(drop=True)

    return forecast_sales(monthly, horizon_months=6)


@router.post("/whatif")
def whatif_simulation(body: WhatIfRequest, db: Session = Depends(get_db)):
    orders = db.query(Order).all()
    if not orders:
        return {"error": "No data available"}

    df = pd.DataFrame([{"order_date": pd.to_datetime(o.order_date), "sales": o.sales} for o in orders])
    df["month"] = df["order_date"].dt.to_period("M")
    monthly = df.groupby("month")["sales"].sum().reset_index()
    monthly["ds"] = monthly["month"].dt.to_timestamp()
    monthly.rename(columns={"sales": "y"}, inplace=True)
    monthly = monthly.sort_values("ds").reset_index(drop=True)

    return simulate_whatif(monthly, body.price_change, body.discount_change, body.marketing_boost)
