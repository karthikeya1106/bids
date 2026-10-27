"""
Data Drift & BPR API.

Combines ADWIN change points, PSI distribution shift, feature-mix drift and a
measured evaluation of each Business Process Rule.
"""
from datetime import datetime
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import BPRRule, KPI
from ml.drift_detector import analyze_feature_drift, analyze_kpi_drift, evaluate_bpr_rules
from security import require_user
from seed_bpr import ensure_bpr_rules
from services.analytics import load_orders_df, monthly_frame, recalculate_kpis
from services.dataset import gate_module
from services.ingestion import active_dataset
from services.modules import build_module

router = APIRouter()


class RuleUpdateRequest(BaseModel):
    status: Optional[str] = None
    rule_description: Optional[str] = None
    action: Optional[str] = None


@router.get("")
def get_drift(
    reference_id: Optional[int] = Query(None, description="Dataset id to use as the drift baseline"),
    db: Session = Depends(get_db),
    owner: str = Depends(require_user),
):
    meta = active_dataset(db, owner)
    if meta is not None and meta.schema_kind != "sales":
        return build_module(db, owner, "drift", reference_id=reference_id)

    blocked = gate_module(db, owner, "drift")
    if blocked:
        return blocked

    df = load_orders_df(db, owner, with_customer=True)

    kpis = db.query(KPI).filter(KPI.owner_id == owner).all()
    if not df.empty:
        ensure_bpr_rules(db, owner)
    rules = [
        {
            "id": rule.id,
            "rule_name": rule.rule_name,
            "rule_description": rule.rule_description,
            "condition_expression": rule.condition_expression,
            "action": rule.action,
            "status": rule.status,
            "effectiveness_score": rule.effectiveness_score,
            "category": rule.category,
            "last_triggered": str(rule.last_triggered) if rule.last_triggered else None,
        }
        for rule in db.query(BPRRule).filter(BPRRule.owner_id == owner).order_by(BPRRule.id).all()
    ]

    if df.empty:
        return {
            "has_data": False,
            "kpis": [],
            "drift_analysis": [],
            "feature_drift": [],
            "bpr_rules": rules,
            "summary": None,
            "generated_at": datetime.utcnow().isoformat(),
        }

    monthly = monthly_frame(df)
    drift_analysis = analyze_kpi_drift(monthly)
    feature_drift = analyze_feature_drift(df)
    evaluated_rules = evaluate_bpr_rules(rules, df)

    kpi_list = [
        {
            "kpi_name": kpi.kpi_name,
            "current_value": kpi.current_value,
            "baseline_value": kpi.baseline_value,
            "target_value": kpi.target_value,
            "drift_score": kpi.drift_score,
            "unit": kpi.unit,
            "gap_pct": round((kpi.current_value - kpi.target_value) / abs(kpi.target_value) * 100, 1)
            if kpi.target_value
            else None,
            "on_target": (
                kpi.current_value >= kpi.target_value
                if kpi.kpi_name != "Churn Rate"
                else kpi.current_value <= kpi.target_value
            ),
            "last_updated": str(kpi.last_updated) if kpi.last_updated else None,
        }
        for kpi in kpis
    ]

    status_counts = {"shifted": 0, "watch": 0, "stable": 0}
    for entry in drift_analysis:
        status_counts[entry["status"]] = status_counts.get(entry["status"], 0) + 1

    shifted_features = [f for f in feature_drift if f["status"] == "significant"]
    measured = [rule for rule in evaluated_rules if rule.get("effectiveness_score") is not None]
    triggered_recently = [
        rule
        for rule in evaluated_rules
        if rule.get("evaluation", {}).get("current_triggered")
    ]

    summary = {
        "kpis_monitored": len(drift_analysis),
        "shifted": status_counts.get("shifted", 0),
        "watching": status_counts.get("watch", 0),
        "stable": status_counts.get("stable", 0),
        "features_tracked": len(feature_drift),
        "features_shifted": len(shifted_features),
        "rules_total": len(evaluated_rules),
        "rules_active": sum(1 for rule in evaluated_rules if rule["status"] == "active"),
        "rules_needing_review": sum(1 for rule in evaluated_rules if rule["status"] == "needs_review"),
        "rules_obsolete": sum(1 for rule in evaluated_rules if rule["status"] == "obsolete"),
        "rules_measurable": len(measured),
        "average_effectiveness": round(
            sum(rule["effectiveness_score"] for rule in measured) / len(measured), 2
        ) if measured else None,
        "rules_triggering_now": len(triggered_recently),
        "period_from": monthly["month"].iloc[0] if not monthly.empty else None,
        "period_to": monthly["month"].iloc[-1] if not monthly.empty else None,
    }

    return {
        "has_data": True,
        "kpis": kpi_list,
        "drift_analysis": drift_analysis,
        "feature_drift": feature_drift,
        "bpr_rules": evaluated_rules,
        "summary": summary,
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.patch("/rules/{rule_id}")
def update_rule(
    rule_id: int,
    body: RuleUpdateRequest,
    db: Session = Depends(get_db),
    owner: str = Depends(require_user),
):
    rule = (
        db.query(BPRRule)
        .filter(BPRRule.id == rule_id, BPRRule.owner_id == owner)
        .first()
    )
    if not rule:
        # Same response for "missing" and "belongs to someone else" so rule ids
        # cannot be probed across workspaces.
        raise HTTPException(status_code=404, detail="Rule not found")

    if body.status:
        if body.status not in {"active", "needs_review", "obsolete"}:
            raise HTTPException(status_code=422, detail="status must be active, needs_review or obsolete")
        rule.status = body.status
    if body.rule_description:
        rule.rule_description = body.rule_description
    if body.action:
        rule.action = body.action

    db.commit()
    db.refresh(rule)
    return {"message": "Rule updated", "rule_id": rule_id, "new_status": rule.status}


@router.post("/recalculate")
def recalculate(db: Session = Depends(get_db), owner: str = Depends(require_user)):
    """Recompute the KPI table from the loaded orders (used after a data upload)."""
    meta = active_dataset(db, owner)
    if meta is None or meta.schema_kind != "sales":
        raise HTTPException(
            status_code=400,
            detail="KPI recalculation applies to sales datasets; this dataset does not use the KPI table.",
        )
    blocked = gate_module(db, owner, "drift")
    if blocked:
        return blocked

    df = load_orders_df(db, owner)
    if df.empty:
        raise HTTPException(status_code=400, detail="No dataset loaded")
    recalculate_kpis(db, owner)
    return {"message": "KPIs recalculated", "orders": int(len(df))}
