"""
Lever optimiser.

The what-if panel scores the levers a user typed in. This module answers the
inverse question — which combination of price, discount and marketing is best —
by grid-searching the *same* simulator, so a recommendation and a manual
scenario can never disagree.

It is deliberately small: the search space and the objective are exposed in the
response, the best point is reported next to the best unconstrained point, and
the grid is bounded so a request stays cheap.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ml.forecaster import forecast_sales, simulate_whatif

PRICE_STEPS = 7
DISCOUNT_STEPS = 5
MARKETING_STEPS = 4


def _steps(low: float, high: float, count: int) -> List[float]:
    values = np.linspace(low, high, count)
    return sorted({round(float(value), 4) for value in values})


def _candidate(price: float, discount: float, marketing: float, result: Dict) -> Dict:
    return {
        "price_change": price,
        "discount_change": discount,
        "marketing_boost": marketing,
        "revenue": result.get("adjusted_total"),
        "revenue_impact": round(float(result.get("adjusted_total", 0)) - float(result.get("base_total", 0)), 2),
        "revenue_impact_pct": result.get("impact_pct"),
        "profit": result.get("adjusted_profit"),
        "profit_impact": result.get("profit_impact"),
        "profit_impact_pct": result.get("profit_impact_pct"),
        "incremental_marketing_spend": (result.get("marketing_spend") or {}).get("incremental", 0),
    }


def _rank(candidate: Dict) -> tuple[float, float]:
    return (float(candidate.get("profit_impact") or 0), float(candidate.get("revenue_impact") or 0))


def optimise_levers(
    monthly_df: pd.DataFrame,
    *,
    horizon_months: int = 6,
    marketing_spend: float = 0.0,
    base: Optional[Dict] = None,
    max_price_change: float = 15.0,
    max_discount_cut: float = 40.0,
    max_marketing_boost: float = 50.0,
    min_revenue_impact_pct: Optional[float] = None,
) -> Dict:
    """Grid-search the simulator for the lever combination with the best profit.

    ``min_revenue_impact_pct`` optionally rejects combinations that would shrink
    revenue by more than that percentage, so a profit gain that comes purely from
    shrinking the business can be refused.
    """
    base = base if base is not None else forecast_sales(monthly_df, horizon_months=horizon_months)
    if not base.get("has_data") or not base.get("forecast"):
        return {
            "has_data": False,
            "error": "No sales history is available to optimise over.",
            "model": base.get("model"),
        }

    price_steps = _steps(-abs(max_price_change), abs(max_price_change), PRICE_STEPS)
    discount_steps = _steps(-abs(max_discount_cut), 0.0, DISCOUNT_STEPS)
    marketing_steps = _steps(0.0, abs(max_marketing_boost), MARKETING_STEPS)

    candidates: List[Dict] = []
    for price in price_steps:
        for discount in discount_steps:
            for marketing in marketing_steps:
                result = simulate_whatif(
                    monthly_df,
                    price,
                    discount,
                    marketing,
                    horizon_months=horizon_months,
                    base=base,
                    marketing_spend=marketing_spend,
                )
                if result.get("error"):
                    continue
                candidates.append(_candidate(price, discount, marketing, result))

    if not candidates:
        return {"has_data": False, "error": "The simulator could not evaluate any lever combination."}

    ranked = sorted(candidates, key=_rank, reverse=True)
    unconstrained = ranked[0]

    # The grid always contains the do-nothing point, so the baseline comes from
    # the same arithmetic as every candidate rather than a separate formula.
    zero = next(
        candidate for candidate in candidates
        if candidate["price_change"] == 0
        and candidate["discount_change"] == 0
        and candidate["marketing_boost"] == 0
    )
    baseline = {
        "revenue": round(float(zero["revenue"] or 0) - float(zero["revenue_impact"] or 0), 2),
        "profit": round(float(zero["profit"] or 0) - float(zero["profit_impact"] or 0), 2),
    }

    feasible = [
        candidate
        for candidate in ranked
        if min_revenue_impact_pct is None
        or float(candidate.get("revenue_impact_pct") or 0) >= float(min_revenue_impact_pct) - 1e-9
    ]
    best = feasible[0] if feasible else None

    alternatives = [
        candidate
        for candidate in ranked
        if best is None or candidate is not best
    ][:4]

    elasticity = base.get("elasticity") or {}
    result_assumptions = simulate_whatif(
        monthly_df,
        0,
        0,
        0,
        horizon_months=horizon_months,
        base=base,
        marketing_spend=marketing_spend,
    ).get("assumptions", {})

    notes = [
        f"Evaluated {len(candidates):,} lever combinations with the same forecast and simulator as the what-if panel.",
        "Each combination is scored on net profit over the horizon; revenue impact is shown alongside it.",
        "Search ranges are the constraints: "
        f"price {price_steps[0]:+.0f}% to {price_steps[-1]:+.0f}%, "
        f"discount level {discount_steps[0]:+.0f}% to {discount_steps[-1]:+.0f}%, "
        f"marketing {marketing_steps[0]:+.0f}% to {marketing_steps[-1]:+.0f}%.",
        "The best point is a grid point, not a continuous optimum, and it is only as good as the demand response it is scored on.",
        "Profit charges the incremental marketing spend only when a spend baseline is supplied."
        if marketing_spend <= 0
        else "Profit charges the incremental marketing spend required by the boost.",
    ]
    if not elasticity.get("measured"):
        notes.append(
            "The demand response is an assumed prior here, so treat the ordering of options as indicative rather than calibrated."
        )
    if min_revenue_impact_pct is not None and best is None:
        notes.append(
            f"No combination kept revenue within {min_revenue_impact_pct:+.1f}%; widen the ranges or relax the floor."
        )
    elif best is not None and unconstrained is not None and best is not unconstrained:
        notes.append(
            "The unconstrained best would shrink revenue past your floor, so a lower-profit combination is recommended instead."
        )

    return {
        "has_data": True,
        "horizon_months": horizon_months,
        "objective": "net profit over the horizon",
        "baseline": baseline,
        "best": best,
        "best_unconstrained": unconstrained,
        "constraint": (
            {"min_revenue_impact_pct": min_revenue_impact_pct} if min_revenue_impact_pct is not None else None
        ),
        "alternatives": alternatives,
        "tradeoff": [
            {
                "price_change": candidate["price_change"],
                "discount_change": candidate["discount_change"],
                "marketing_boost": candidate["marketing_boost"],
                "revenue_impact_pct": candidate["revenue_impact_pct"],
                "profit_impact": candidate["profit_impact"],
            }
            for candidate in candidates
        ],
        "search": {
            "price_change": price_steps,
            "discount_change": discount_steps,
            "marketing_boost": marketing_steps,
            "combinations": len(candidates),
        },
        "elasticity": {
            **elasticity,
            "value_used": elasticity.get("value"),
        },
        "assumptions": result_assumptions,
        "notes": notes,
    }
