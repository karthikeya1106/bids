from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from db.database import get_db
from db.models import Order
from ml.segmentation import run_segmentation
import pandas as pd

router = APIRouter()


@router.get("")
def get_segments(db: Session = Depends(get_db)):
    orders = db.query(Order).all()
    if not orders:
        return {"segments": [], "top_customers": [], "total_customers": 0}

    df = pd.DataFrame([{
        "order_id": o.order_id, "customer_id": o.customer_id,
        "order_date": o.order_date, "sales": o.sales,
    } for o in orders])

    result = run_segmentation(df)
    return result
