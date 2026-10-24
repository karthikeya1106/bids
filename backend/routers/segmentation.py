from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import pandas as pd

from db.database import get_db
from db.models import Customer
from ml.segmentation import run_segmentation
from security import require_user
from services.analytics import load_orders_df

router = APIRouter()


@router.get("")
def get_segments(db: Session = Depends(get_db), owner: str = Depends(require_user)):
    orders = load_orders_df(db, owner)
    if orders.empty:
        return {
            "has_data": False,
            "segments": [],
            "top_customers": [],
            "total_customers": 0,
            "total_revenue": 0.0,
            "averages": {},
        }

    customers = db.query(Customer).filter(Customer.owner_id == owner).all()
    customers_df = pd.DataFrame(
        [
            {
                "customer_id": c.customer_id,
                "customer_name": c.customer_name or c.customer_id,
                "segment": c.segment or "Unknown",
                "region": c.region or "Unknown",
                "state": c.state or "Unknown",
            }
            for c in customers
        ]
    )

    result = run_segmentation(orders, customers_df)
    return {"has_data": True, **result}
