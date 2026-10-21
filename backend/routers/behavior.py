from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from db.database import get_db
from db.models import Order, Customer
import pandas as pd
import numpy as np

router = APIRouter()


@router.get("")
def get_behavior(db: Session = Depends(get_db)):
    orders = db.query(Order).all()
    customers = db.query(Customer).all()

    if not orders:
        return _mock_behavior()

    df = pd.DataFrame([{
        "order_id": o.order_id, "order_date": pd.to_datetime(o.order_date),
        "customer_id": o.customer_id, "sales": o.sales,
        "quantity": o.quantity, "category": o.category, "sub_category": o.sub_category,
    } for o in orders])

    cust_df = pd.DataFrame([{"customer_id": c.customer_id, "segment": c.segment, "region": c.region} for c in customers])

    # Heatmap: day of week vs hour (simulated)
    df["day_of_week"] = df["order_date"].dt.dayofweek
    df["month"] = df["order_date"].dt.month
    heatmap = df.groupby(["day_of_week", "month"])["sales"].sum().reset_index()
    heatmap_data = {
        "x": list(range(1, 13)),
        "y": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "z": [
            [round(heatmap[(heatmap["day_of_week"] == d) & (heatmap["month"] == m)]["sales"].sum(), 2)
             for m in range(1, 13)]
            for d in range(7)
        ]
    }

    # Funnel
    total_customers = df["customer_id"].nunique()
    repeat_customers = df.groupby("customer_id")["order_id"].nunique()
    repeat_count = int((repeat_customers > 1).sum())
    loyal_count = int((repeat_customers > 3).sum())

    funnel = [
        {"stage": "Awareness", "value": total_customers * 4},
        {"stage": "First Purchase", "value": total_customers},
        {"stage": "Repeat Buyer", "value": repeat_count},
        {"stage": "Loyal Customer", "value": loyal_count},
    ]

    # CLV by segment
    merged = df.merge(cust_df, on="customer_id", how="left")
    clv_by_segment = merged.groupby("segment")["sales"].sum().reset_index()
    clv_by_segment["clv"] = (clv_by_segment["sales"] / total_customers).round(2)

    # Retention metrics
    retention_rate = round(repeat_count / max(total_customers, 1) * 100, 1)
    churn_rate = round(100 - retention_rate, 1)

    # Top sub-categories
    top_sub = df.groupby("sub_category")["sales"].sum().nlargest(8).reset_index()
    top_products = [{"name": r["sub_category"], "sales": round(r["sales"], 2)} for _, r in top_sub.iterrows()]

    # Purchase frequency distribution
    freq_dist = repeat_customers.value_counts().sort_index().head(10)
    frequency = [{"purchases": int(k), "customers": int(v)} for k, v in freq_dist.items()]

    return {
        "heatmap": heatmap_data,
        "funnel": funnel,
        "clv_by_segment": clv_by_segment.to_dict(orient="records"),
        "retention_rate": retention_rate,
        "churn_rate": churn_rate,
        "top_products": top_products,
        "frequency_distribution": frequency,
        "total_customers": total_customers,
        "repeat_customers": repeat_count,
        "loyal_customers": loyal_count,
    }


def _mock_behavior():
    return {
        "heatmap": {"x": list(range(1, 13)), "y": ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"], "z": [[0]*12]*7},
        "funnel": [{"stage":"Awareness","value":3200},{"stage":"First Purchase","value":800},{"stage":"Repeat Buyer","value":320},{"stage":"Loyal Customer","value":89}],
        "clv_by_segment": [{"segment":"Consumer","clv":1200},{"segment":"Corporate","clv":2400},{"segment":"Home Office","clv":980}],
        "retention_rate": 67.4, "churn_rate": 32.6,
        "top_products": [], "frequency_distribution": [], "total_customers": 0, "repeat_customers": 0, "loyal_customers": 0,
    }
