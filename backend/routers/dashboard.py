from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from db.database import get_db
from db.models import Order, Customer, KPI
import pandas as pd

router = APIRouter()


@router.get("")
def get_dashboard(db: Session = Depends(get_db)):
    orders = db.query(Order).all()
    if not orders:
        return _mock_dashboard()

    df = pd.DataFrame([{
        "order_id": o.order_id, "order_date": o.order_date,
        "sales": o.sales, "profit": o.profit, "quantity": o.quantity,
        "customer_id": o.customer_id, "category": o.category,
    } for o in orders])

    total_sales = round(df["sales"].sum(), 2)
    total_profit = round(df["profit"].sum(), 2)
    total_orders = df["order_id"].nunique()
    total_customers = df["customer_id"].nunique()
    avg_order_value = round(total_sales / max(total_orders, 1), 2)
    profit_margin = round(total_profit / max(total_sales, 1) * 100, 2)

    # Monthly revenue trend
    df["order_date"] = pd.to_datetime(df["order_date"])
    df["month"] = df["order_date"].dt.to_period("M")
    monthly = df.groupby("month").agg(sales=("sales", "sum"), profit=("profit", "sum")).reset_index()
    monthly["month"] = monthly["month"].astype(str)

    revenue_trend = [{"month": r["month"], "sales": round(r["sales"], 2), "profit": round(r["profit"], 2)}
                     for _, r in monthly.iterrows()]

    # Category breakdown
    cat_sales = df.groupby("category")["sales"].sum().reset_index()
    category_breakdown = [{"category": r["category"], "sales": round(r["sales"], 2)}
                          for _, r in cat_sales.iterrows()]

    # Alerts
    kpis = db.query(KPI).all()
    alerts = []
    for k in kpis:
        if k.drift_score and k.drift_score > 0.3:
            alerts.append({"type": "drift", "message": f"Drift detected in {k.kpi_name} (score: {k.drift_score:.0%})", "severity": "warning"})
        if k.current_value and k.target_value and k.current_value < k.target_value * 0.85:
            alerts.append({"type": "kpi", "message": f"{k.kpi_name} is {round((1 - k.current_value/k.target_value)*100,1)}% below target", "severity": "danger"})

    return {
        "kpis": {
            "total_sales": total_sales,
            "total_profit": total_profit,
            "total_orders": total_orders,
            "total_customers": total_customers,
            "avg_order_value": avg_order_value,
            "profit_margin": profit_margin,
        },
        "revenue_trend": revenue_trend[-24:],
        "category_breakdown": category_breakdown,
        "alerts": alerts[:6],
    }


def _mock_dashboard():
    return {
        "kpis": {
            "total_sales": 2297201.0, "total_profit": 286397.0,
            "total_orders": 4922, "total_customers": 793,
            "avg_order_value": 457.5, "profit_margin": 12.47,
        },
        "revenue_trend": [],
        "category_breakdown": [
            {"category": "Technology", "sales": 836154.0},
            {"category": "Furniture", "sales": 741999.0},
            {"category": "Office Supplies", "sales": 719047.0},
        ],
        "alerts": [{"type": "kpi", "message": "No data seeded yet. Run python -m db.seed", "severity": "warning"}],
    }
