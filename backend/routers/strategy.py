from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from db.database import get_db
from db.models import KPI, BPRRule, Order
from ml.strategy_llm import get_gemini_recommendations
from ml.segmentation import run_segmentation
from ml.drift_detector import analyze_kpi_drift
import pandas as pd

router = APIRouter()


@router.post("")
def get_strategy(db: Session = Depends(get_db)):
    kpis = db.query(KPI).all()
    rules = db.query(BPRRule).all()
    orders = db.query(Order).all()

    kpi_list = [{"kpi_name": k.kpi_name, "current_value": k.current_value,
                 "target_value": k.target_value, "drift_score": k.drift_score, "unit": k.unit}
                for k in kpis]

    segments_data = []
    drift_analysis = []

    if orders:
        df = pd.DataFrame([{"order_id": o.order_id, "customer_id": o.customer_id,
                             "order_date": o.order_date, "sales": o.sales} for o in orders])
        seg_result = run_segmentation(df)
        segments_data = seg_result.get("segments", [])

        df2 = pd.DataFrame([{"order_date": pd.to_datetime(o.order_date), "sales": o.sales,
                              "profit": o.profit, "order_id": o.order_id} for o in orders])
        df2["month"] = df2["order_date"].dt.to_period("M")
        monthly = df2.groupby("month").agg(
            sales=("sales", "sum"), profit=("profit", "sum"), orders=("order_id", "nunique")
        ).reset_index()
        monthly["ds"] = monthly["month"].dt.to_timestamp()
        drift_analysis = analyze_kpi_drift(monthly)

    recommendations = get_gemini_recommendations(kpi_list, segments_data, drift_analysis)

    return {
        "recommendations": recommendations,
        "generated_by": "Google Gemini AI" if len(recommendations) > 0 else "Rule Engine",
        "context_snapshot": {
            "kpis_analyzed": len(kpi_list),
            "segments_analyzed": len(segments_data),
            "drift_signals": sum(1 for d in drift_analysis if d.get("drift_detected")),
        }
    }
