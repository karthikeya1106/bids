from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from db.database import get_db
from db.models import Order
from ml.root_cause import detect_anomalies, build_fishbone
import pandas as pd

router = APIRouter()


@router.get("")
def get_rootcause(db: Session = Depends(get_db)):
    orders = db.query(Order).all()
    if not orders:
        return _mock_rootcause()

    df = pd.DataFrame([{"order_date": pd.to_datetime(o.order_date), "sales": o.sales} for o in orders])
    df["month"] = df["order_date"].dt.to_period("M")
    monthly = df.groupby("month")["sales"].sum().reset_index()
    monthly["ds"] = monthly["month"].dt.to_timestamp()
    monthly.rename(columns={"sales": "y"}, inplace=True)
    monthly = monthly.sort_values("ds").reset_index(drop=True)

    anomalies = detect_anomalies(monthly)
    anomaly_months = [a["date"] for a in anomalies]
    fishbone = build_fishbone(df, anomaly_months)

    return {
        "monthly_series": [{"date": str(r["ds"])[:7], "value": round(r["y"], 2)} for _, r in monthly.iterrows()],
        "anomalies": anomalies,
        **fishbone,
    }


def _mock_rootcause():
    return {
        "monthly_series": [], "anomalies": [],
        "fishbone": {
            "People": [{"factor": "No data", "confidence": 0, "evidence": "Seed database to view analysis"}],
            "Process": [], "Product": [], "External": [],
        },
        "top_root_cause": {"branch": "N/A", "factor": "No data", "confidence": 0, "evidence": ""},
        "anomaly_months": [],
    }
