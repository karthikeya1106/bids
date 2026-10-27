"""
Strategy API.

``GET /api/strategy/insights`` computes measured opportunities from the dataset
(no external API required). ``POST /api/strategy`` adds a Gemini narrative when a
key is configured and always falls back to the measured playbook.
"""
from datetime import datetime

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import BPRRule, KPI
from ml.drift_detector import analyze_kpi_drift, evaluate_bpr_rules
from ml.segmentation import run_segmentation
from ml.strategy_llm import (
    build_playbook,
    get_gemini_recommendations,
    recommendations_from_plays,
)
from security import require_user
from seed_bpr import ensure_bpr_rules
from services.analytics import load_orders_df, monthly_frame
from services.dataset import gate_module
from services.ingestion import active_dataset
from services.modules import build_module
from services.scenarios import simulate_plays

router = APIRouter()

DEEP_DISCOUNT = 0.20


class ScenarioRequest(BaseModel):
    horizon_months: int = Field(6, ge=3, le=12)
    marketing_spend: float = Field(0, ge=0, le=50_000_000)


def _collect(db: Session, owner: str):
    df = load_orders_df(db, owner, with_customer=True)
    if df.empty:
        return None
    ensure_bpr_rules(db, owner)

    kpis = [
        {
            "kpi_name": kpi.kpi_name,
            "current_value": kpi.current_value,
            "baseline_value": kpi.baseline_value,
            "target_value": kpi.target_value,
            "drift_score": kpi.drift_score,
            "unit": kpi.unit,
        }
        for kpi in db.query(KPI).filter(KPI.owner_id == owner).all()
    ]

    segments = run_segmentation(df).get("segments", [])
    drift = analyze_kpi_drift(monthly_frame(df))

    rule_rows = [
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
    rules = evaluate_bpr_rules(rule_rows, df)

    total_revenue = float(df["sales"].sum())
    total_profit = float(df["profit"].sum())

    # Opportunities are sized on the trailing 12 months, not on lifetime history,
    # so a play's dollar impact is an annual figure the reader can act on.
    anchor = df["order_date"].max()
    recent = df[df["order_date"] > anchor - pd.Timedelta(days=365)]
    recent_revenue = float(recent["sales"].sum())
    recent_profit = float(recent["profit"].sum())
    margin = round(recent_profit / recent_revenue * 100, 2) if recent_revenue else 0.0

    window_start = anchor - pd.Timedelta(days=90)
    first_order = df.groupby("customer_id")["order_date"].min()
    new_ids = set(first_order[first_order > window_start].index)
    new_revenue = float(
        df[(df["customer_id"].isin(new_ids)) & (df["order_date"] > window_start)]["sales"].sum()
    )

    repeat_counts = df.groupby("customer_id")["order_id"].nunique()
    repeat_rate = (
        round(float((repeat_counts > 1).sum()) / len(repeat_counts) * 100, 1)
        if len(repeat_counts)
        else 0.0
    )

    deep = recent[recent["discount"] > DEEP_DISCOUNT]
    deep_revenue = float(deep["sales"].sum())
    deep_profit = float(deep["profit"].sum())
    discount_stats = {
        "revenue": deep_revenue,
        "profit": deep_profit,
        "margin": round(deep_profit / deep_revenue * 100, 1) if deep_revenue else 0.0,
        "share": round(deep_revenue / recent_revenue * 100, 1) if recent_revenue else 0.0,
    }

    by_customer = recent.groupby("customer_id")["sales"].sum().sort_values(ascending=False)
    top10_revenue = float(by_customer.head(10).sum())
    concentration = {
        "top10_revenue": top10_revenue,
        "top10_share": round(top10_revenue / recent_revenue * 100, 1) if recent_revenue else 0.0,
    }

    by_subcategory = (
        recent.groupby("sub_category")
        .agg(sales=("sales", "sum"), profit=("profit", "sum"))
        .reset_index()
        .sort_values("profit")
    )
    loss_makers = [
        {
            "name": str(row.sub_category),
            "sales": round(float(row.sales), 2),
            "profit": round(float(row.profit), 2),
        }
        for row in by_subcategory[by_subcategory["profit"] < 0].head(4).itertuples(index=False)
    ]

    at_risk = next((s for s in segments if s["name"] == "At-Risk"), {})
    champions = next((s for s in segments if s["name"] == "Champions"), {})

    stats = {
        "total_revenue": total_revenue,
        "total_profit": total_profit,
        "recent_revenue": recent_revenue,
        "margin": margin,
        "repeat_rate": repeat_rate,
        "discount": discount_stats,
        "concentration": concentration,
        "loss_makers": loss_makers,
        "at_risk": {
            "count": at_risk.get("count", 0),
            "revenue": round(recent_revenue * at_risk.get("revenue_share", 0.0) / 100, 2),
            "lifetime_revenue": at_risk.get("revenue", 0.0),
            "revenue_share": at_risk.get("revenue_share", 0.0),
            "avg_monetary": at_risk.get("avg_monetary", 0.0),
            "avg_recency": at_risk.get("avg_recency", 0.0),
        },
        "champions": {
            "count": champions.get("count", 0),
            "revenue": round(recent_revenue * champions.get("revenue_share", 0.0) / 100, 2),
            "lifetime_revenue": champions.get("revenue", 0.0),
            "revenue_share": champions.get("revenue_share", 0.0),
            "avg_monetary": champions.get("avg_monetary", 0.0),
        },
        "acquisition": {
            "new_customers": len(new_ids),
            "new_revenue": new_revenue,
        },
        "rules_total": len(rules),
        "rules_needing_review": sum(1 for rule in rules if rule["status"] == "needs_review"),
        "rules_triggering": sum(
            1 for rule in rules if rule.get("evaluation", {}).get("current_triggered")
        ),
    }

    return {
        "df": df,
        "kpis": kpis,
        "segments": segments,
        "drift": drift,
        "rules": rules,
        "stats": stats,
    }


@router.get("/insights")
def get_insights(db: Session = Depends(get_db), owner: str = Depends(require_user)):
    meta = active_dataset(db, owner)
    if meta is not None and meta.schema_kind != "sales":
        return build_module(db, owner, "strategy")

    blocked = gate_module(db, owner, "strategy")
    if blocked:
        return blocked

    collected = _collect(db, owner)
    if collected is None:
        return {
            "has_data": False,
            "plays": [],
            "summary": None,
            "generated_at": datetime.utcnow().isoformat(),
        }

    plays = build_playbook(collected["stats"])
    summary = {
        "plays": len(plays),
        "p1_count": sum(1 for play in plays if play["priority"] == "P1"),
        "revenue_opportunity": round(
            sum(play["impact_value"] for play in plays if play["impact_type"] == "revenue"), 2
        ),
        "profit_opportunity": round(
            sum(play["impact_value"] for play in plays if play["impact_type"] == "profit"), 2
        ),
        "segments_analyzed": len(collected["segments"]),
        "drift_signals": sum(1 for entry in collected["drift"] if entry["status"] == "shifted"),
        "kpis_analyzed": len(collected["kpis"]),
        "generated_by": "Measured playbook",
    }

    return {
        "has_data": True,
        "plays": plays,
        "summary": summary,
        "focus": {
            "at_risk": collected["stats"]["at_risk"],
            "champions": collected["stats"]["champions"],
            "deep_discount": collected["stats"]["discount"],
            "concentration": collected["stats"]["concentration"],
        },
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.post("/scenarios")
def get_play_scenarios(
    body: ScenarioRequest,
    db: Session = Depends(get_db),
    owner: str = Depends(require_user),
):
    """Evaluate each measured play as a demand-simulator scenario.

    The playbook's annual estimate says what is at stake; this says what the
    play's own mechanism would do to revenue and net profit over the horizon, and
    how far that moves when the price elasticity is uncertain.
    """
    meta = active_dataset(db, owner)
    if meta is None or meta.schema_kind != "sales":
        raise HTTPException(
            status_code=400,
            detail=(
                "Play scenarios are simulated on sales revenue. This dataset does not "
                "have a sales timeline."
            ),
        )

    collected = _collect(db, owner)
    if collected is None:
        return {
            "has_data": False,
            "available": False,
            "reason": "No sales rows are stored for this workspace.",
            "plays": {},
            "simulation": None,
        }

    df = collected["df"]
    monthly = monthly_frame(df)
    series = pd.DataFrame(
        {
            "ds": pd.to_datetime(monthly["month"].astype(str) + "-01"),
            "y": monthly["sales"].astype(float),
        }
    )
    plays = build_playbook(collected["stats"])
    return {
        "has_data": True,
        **simulate_plays(
            series,
            df,
            plays,
            horizon_months=body.horizon_months,
            marketing_spend=body.marketing_spend,
        ),
    }


@router.post("")
def get_strategy(db: Session = Depends(get_db), owner: str = Depends(require_user)):
    meta = active_dataset(db, owner)
    if meta is not None and meta.schema_kind != "sales":
        payload = build_module(db, owner, "strategy")
        payload.setdefault("recommendations", [])
        payload.setdefault("plays", payload.get("sections", []))
        payload.setdefault("generated_by", "Measured associations")
        payload["ai_available"] = False
        return payload

    blocked = gate_module(db, owner, "strategy")
    if blocked:
        return blocked

    collected = _collect(db, owner)
    if collected is None:
        return {"recommendations": [], "plays": [], "generated_by": "No data"}

    plays = build_playbook(collected["stats"])
    ai_recommendations = get_gemini_recommendations(
        collected["kpis"], collected["segments"], collected["drift"], plays
    )

    return {
        "recommendations": ai_recommendations or recommendations_from_plays(plays),
        "plays": plays,
        "ai_available": ai_recommendations is not None,
        "generated_by": "Google Gemini" if ai_recommendations else "Measured playbook",
        "context_snapshot": {
            "kpis_analyzed": len(collected["kpis"]),
            "segments_analyzed": len(collected["segments"]),
            "drift_signals": sum(1 for entry in collected["drift"] if entry["status"] == "shifted"),
            "plays_measured": len(plays),
            "orders": int(len(collected["df"])),
        },
    }
