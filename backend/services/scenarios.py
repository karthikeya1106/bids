"""
Play scenarios.

The playbook ranks opportunities with a measured annual estimate, but that
estimate does not answer "what happens if we do this?" for the forecast horizon.
This module answers that: it maps each play onto the demand simulator's levers
(price, discount, marketing), runs the same base forecast the Forecast tab uses,
and reports the revenue and net-profit impact — plus how far that impact moves
when the price elasticity is uncertain.

Three rules keep the output honest:

* the levers are an explicit *proxy* for the play's mechanism, and every
  scenario carries the proxy it used, so nobody reads it as the play's exact
  operating plan;
* the sensitivity range comes from the elasticity confidence band, not from an
  invented range, and comes with the fit quality that produced it;
* plays whose mechanism is not price/discount/marketing (retention planning,
  process hygiene) return no scenario and say why, rather than being forced into
  levers that do not describe them.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from ml.forecaster import ELASTICITY_PRIOR, forecast_sales, simulate_whatif

# play id → simulator levers (percent changes) and the proxy it represents.
PLAY_SCENARIOS: Dict[str, Dict] = {
    "win-back-at-risk": {
        "levers": {"price_change": 0, "discount_change": 10, "marketing_boost": 25},
        "rationale": (
            "Modelled as a 25% marketing boost plus a 10% deeper discount for the "
            "reactivation sequence. Win-back targeting itself is not a simulator lever."
        ),
    },
    "cap-deep-discounts": {
        "levers": {"price_change": 0, "discount_change": -25, "marketing_boost": 0},
        "rationale": (
            "Capping discounts above 20% is proxied by a 25% reduction in the "
            "portfolio discount level."
        ),
    },
    "reprice-loss-makers": {
        "levers": {"price_change": 5, "discount_change": 0, "marketing_boost": 0},
        "rationale": (
            "Recosting the loss-making lines is proxied by a 5% price increase across "
            "the portfolio; the actual repricing would be SKU-specific."
        ),
    },
    "expand-champions": {
        "levers": {"price_change": 3, "discount_change": 0, "marketing_boost": 10},
        "rationale": (
            "Bundling and a premium tier are proxied by a 3% price uplift plus a 10% "
            "marketing boost; wallet-share gains beyond that are not modelled."
        ),
    },
    "activate-new-customers": {
        "levers": {"price_change": 0, "discount_change": 5, "marketing_boost": 20},
        "rationale": (
            "The second-order incentive is proxied by a 20% marketing boost and a 5% "
            "deeper discount."
        ),
    },
}

# Plays whose mechanism no price/discount/marketing lever describes.
NO_SCENARIO_REASON = {
    "protect-key-accounts": (
        "This play protects revenue through account planning and service levels, not "
        "through price, discount or marketing, so the simulator has no lever for it."
    ),
    "review-bpr-rules": (
        "This play is process hygiene and carries no dollar impact, so there is "
        "nothing to simulate."
    ),
}


def _empty(reason: str) -> Dict:
    return {"available": False, "reason": reason, "plays": {}, "simulation": None}


def simulate_plays(
    series: pd.DataFrame,
    orders_df: pd.DataFrame,
    plays: List[Dict],
    horizon_months: int = 6,
    marketing_spend: float = 0.0,
) -> Dict:
    """Run each play through the simulator and return per-play scenarios."""
    base = forecast_sales(series, horizon_months=horizon_months, orders_df=orders_df)
    if not base.get("has_data") or not base.get("forecast"):
        return _empty(
            "There is not enough monthly history to forecast a baseline, so the plays "
            "cannot be simulated."
        )

    elasticity = base.get("elasticity") or {}
    band = elasticity.get("band") or [ELASTICITY_PRIOR * 0.7, ELASTICITY_PRIOR * 1.3]
    low_elasticity, high_elasticity = float(band[0]), float(band[1])
    if low_elasticity > high_elasticity:
        low_elasticity, high_elasticity = high_elasticity, low_elasticity
    spend = max(float(marketing_spend or 0.0), 0.0)

    scenarios: Dict[str, Dict] = {}
    for play in plays:
        play_id = str(play.get("id"))
        spec = PLAY_SCENARIOS.get(play_id)
        if spec is None:
            scenarios[play_id] = {
                "available": False,
                "reason": NO_SCENARIO_REASON.get(
                    play_id, "This play does not map onto a price, discount or marketing lever."
                ),
            }
            continue

        levers = dict(spec["levers"])
        central = simulate_whatif(
            series,
            levers["price_change"],
            levers["discount_change"],
            levers["marketing_boost"],
            horizon_months=horizon_months,
            base=base,
            marketing_spend=spend,
        )
        low = simulate_whatif(
            series,
            levers["price_change"],
            levers["discount_change"],
            levers["marketing_boost"],
            horizon_months=horizon_months,
            base=base,
            marketing_spend=spend,
            elasticity_value=low_elasticity,
        )
        high = simulate_whatif(
            series,
            levers["price_change"],
            levers["discount_change"],
            levers["marketing_boost"],
            horizon_months=horizon_months,
            base=base,
            marketing_spend=spend,
            elasticity_value=high_elasticity,
        )
        if central.get("error"):
            scenarios[play_id] = {"available": False, "reason": central["error"]}
            continue

        revenue_impacts = [
            item["adjusted_total"] - item["base_total"] for item in (low, high)
        ]
        profit_impacts = [item["profit_impact"] for item in (low, high)]
        marketing_spend_info = central.get("marketing_spend") or {}

        scenarios[play_id] = {
            "available": True,
            "levers": levers,
            "rationale": spec["rationale"],
            "horizon_months": horizon_months,
            "base_revenue": central["base_total"],
            "scenario_revenue": central["adjusted_total"],
            "revenue_impact": round(central["adjusted_total"] - central["base_total"], 2),
            "revenue_impact_pct": central["impact_pct"],
            "base_profit": central["base_profit"],
            "scenario_profit": central["adjusted_profit"],
            "profit_impact": central["profit_impact"],
            "profit_impact_pct": central["profit_impact_pct"],
            "marketing_cost": marketing_spend_info.get("incremental", 0.0),
            "sensitivity": {
                "elasticity_low": low_elasticity,
                "elasticity_central": central["assumptions"]["price_elasticity"],
                "elasticity_high": high_elasticity,
                "revenue_impact_range": [
                    round(min(revenue_impacts), 2),
                    round(max(revenue_impacts), 2),
                ],
                "profit_impact_range": [
                    round(min(profit_impacts), 2),
                    round(max(profit_impacts), 2),
                ],
                "basis": (
                    "elasticity confidence band (slope ± 1.96 standard errors)"
                    if elasticity.get("measured")
                    else "documented prior range, because the elasticity was assumed"
                ),
            },
            "assumptions": {
                key: central["assumptions"][key]
                for key in (
                    "price_elasticity",
                    "elasticity_measured",
                    "elasticity_source",
                    "elasticity_sample",
                    "elasticity_r2",
                    "elasticity_note",
                    "new_discount_pct",
                    "marketing_lift_pct",
                    "marketing_spend_basis",
                    "incremental_marketing_spend",
                    "marketing_spend_not_deducted",
                )
                if key in central["assumptions"]
            },
        }

    simulated = sum(1 for item in scenarios.values() if item.get("available"))
    return {
        "available": True,
        "horizon_months": horizon_months,
        "plays": scenarios,
        "simulation": {
            "baseline_revenue": round(sum(item["value"] for item in base["forecast"]), 2),
            "horizon_months": horizon_months,
            "model": base.get("model"),
            "marketing_spend_basis": round(spend, 2),
            "marketing_spend_charged": bool(spend > 0),
            "elasticity": {
                "value": elasticity.get("value"),
                "measured": bool(elasticity.get("measured")),
                "method": elasticity.get("method"),
                "sample": elasticity.get("sample"),
                "r2": elasticity.get("r2"),
                "stderr": elasticity.get("stderr"),
                "band": [low_elasticity, high_elasticity],
                "reason": elasticity.get("reason"),
            },
            "plays_simulated": simulated,
            "plays_without_scenario": len(plays) - simulated,
        },
    }
