from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from db.database import get_db
from db.models import KPI, BPRRule, Order
from ml.drift_detector import analyze_kpi_drift
import pandas as pd
from typing import Optional

router = APIRouter()


class RuleUpdateRequest(BaseModel):
    status: Optional[str] = None
    rule_description: Optional[str] = None
    action: Optional[str] = None


@router.get("")
def get_drift(db: Session = Depends(get_db)):
    orders = db.query(Order).all()
    kpis = db.query(KPI).all()
    rules = db.query(BPRRule).all()

    kpi_list = [
        {
            "kpi_name": k.kpi_name, "current_value": k.current_value,
            "baseline_value": k.baseline_value, "target_value": k.target_value,
            "drift_score": k.drift_score, "unit": k.unit,
        }
        for k in kpis
    ]

    rules_list = [
        {
            "id": r.id, "rule_name": r.rule_name, "rule_description": r.rule_description,
            "condition_expression": r.condition_expression, "action": r.action,
            "status": r.status, "effectiveness_score": r.effectiveness_score, "category": r.category,
        }
        for r in rules
    ]

    drift_analysis = []
    if orders:
        df = pd.DataFrame([{"order_date": pd.to_datetime(o.order_date), "sales": o.sales,
                             "profit": o.profit, "order_id": o.order_id} for o in orders])
        df["month"] = df["order_date"].dt.to_period("M")
        monthly = df.groupby("month").agg(
            sales=("sales", "sum"), profit=("profit", "sum"), orders=("order_id", "nunique")
        ).reset_index()
        monthly["ds"] = monthly["month"].dt.to_timestamp()
        drift_analysis = analyze_kpi_drift(monthly)

    return {
        "kpis": kpi_list,
        "bpr_rules": rules_list,
        "drift_analysis": drift_analysis,
        "active_rules": sum(1 for r in rules if r.status == "active"),
        "rules_needing_review": sum(1 for r in rules if r.status == "needs_review"),
        "obsolete_rules": sum(1 for r in rules if r.status == "obsolete"),
    }


@router.patch("/rules/{rule_id}")
def update_rule(rule_id: int, body: RuleUpdateRequest, db: Session = Depends(get_db)):
    rule = db.query(BPRRule).filter(BPRRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    if body.status:
        rule.status = body.status
    if body.rule_description:
        rule.rule_description = body.rule_description
    if body.action:
        rule.action = body.action

    db.commit()
    db.refresh(rule)
    return {"message": "Rule updated", "rule_id": rule_id, "new_status": rule.status}
