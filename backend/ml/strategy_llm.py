"""
Strategy engine.

Two layers:

1. **Measured playbook** — deterministic opportunities computed from the loaded
   dataset (segment revenue at stake, discount leakage, loss-making lines,
   concentration, new-customer activation). Every play carries the numbers it was
   derived from, so the page is useful without any external API.
2. **Gemini narrative** — when ``GEMINI_API_KEY`` is configured the measured
   plays are passed to Gemini so it can prioritise and phrase them. Any failure
   falls back to the playbook; the UI always gets a complete answer.
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


# ── formatting helpers ───────────────────────────────────────────────────────
def _money(value: float) -> str:
    value = float(value or 0)
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000:
        return f"{sign}${value / 1_000_000:.1f}M"
    if value >= 10_000:
        return f"{sign}${value / 1_000:,.0f}K"
    if value >= 1_000:
        return f"{sign}${value / 1_000:,.1f}K"
    return f"{sign}${value:,.0f}"


def _priority(impact: float, confidence: float) -> str:
    if impact >= 25_000 or (impact >= 10_000 and confidence >= 0.7):
        return "P1"
    if impact >= 5_000:
        return "P2"
    return "P3"


def _play(
    key: str,
    title: str,
    description: str,
    category: str,
    impact_value: float,
    impact_type: str,
    confidence: float,
    risk_level: str,
    horizon: str,
    evidence: List[str],
    actions: List[str],
) -> Dict:
    impact_value = round(max(float(impact_value), 0.0), 2)
    return {
        "id": key,
        "title": title,
        "description": description,
        "category": category,
        "impact_value": impact_value,
        "impact_type": impact_type,
        "impact_label": (
            "Operational hygiene" if impact_type == "efficiency"
            else f"≈ {_money(impact_value)} {impact_type}"
        ),
        "confidence": round(confidence, 2),
        "risk_level": risk_level,
        "horizon": horizon,
        "priority": _priority(impact_value, confidence),
        "evidence": [item for item in evidence if item],
        "actions": actions,
        "source": "measured",
    }


# ── measured playbook ────────────────────────────────────────────────────────
def build_playbook(stats: Dict) -> List[Dict]:
    """Turn measured business statistics into a ranked list of plays."""
    plays: List[Dict] = []
    total_revenue = float(stats.get("total_revenue") or 0)

    at_risk = stats.get("at_risk") or {}
    if at_risk.get("revenue", 0) > 0:
        recovery = at_risk["revenue"] * 0.15
        plays.append(
            _play(
                "win-back-at-risk",
                f"Win back {at_risk.get('count', 0):,} at-risk customers",
                "Run a three-touch reactivation sequence on the segment that still carries real "
                "revenue but has gone quiet. Lead with the sub-categories they used to buy.",
                "Revenue recovery",
                recovery,
                "revenue",
                0.72,
                "low",
                "12 months",
                [
                    f"At-Risk accounts for {at_risk.get('revenue_share', 0):.1f}% of trailing-12-month "
                    f"revenue (≈{_money(at_risk.get('revenue', 0))}) across "
                    f"{at_risk.get('count', 0):,} customers.",
                    f"Average lifetime spend {_money(at_risk.get('avg_monetary', 0))} and "
                    f"{at_risk.get('avg_recency', 0):.0f} days since the last order.",
                    "15% win-back of their trailing revenue is assumed.",
                ],
                [
                    "Email → SMS → personal offer over 21 days",
                    "Personalise the offer with each customer's top category",
                    "Escalate accounts above $10k lifetime spend to an account manager",
                ],
            )
        )

    discount = stats.get("discount") or {}
    if discount.get("revenue", 0) > 0:
        # When deep-discount lines are loss-making, the opportunity is recovering
        # part of that loss; otherwise it is the margin from a 3pp price recovery.
        deep_profit = float(discount.get("profit", 0))
        recovery = abs(deep_profit) * 0.4 if deep_profit < 0 else discount["revenue"] * 0.03
        plays.append(
            _play(
                "cap-deep-discounts",
                "Cap discounts above 20%",
                "Deep-discount lines are destroying margin rather than buying profitable volume. "
                "Move approval above 20% to a manager and redirect the discount budget to targeted offers.",
                "Pricing",
                recovery,
                "profit",
                0.78,
                "medium",
                "12 months",
                [
                    f"{_money(discount.get('revenue', 0))} of trailing-12-month revenue "
                    f"({discount.get('share', 0):.1f}% of the total) is booked above a 20% discount.",
                    f"That revenue is loss-making: {_money(discount.get('profit', 0))} "
                    f"({discount.get('margin', 0):.1f}% margin) versus "
                    f"{stats.get('margin', 0):.1f}% for the portfolio.",
                    "Recovering 40% of the loss through a discount cap is assumed." if deep_profit < 0
                    else "A 3pp discount reduction on those lines is worth the impact shown.",
                ],
                [
                    "Set an approval step for discounts above 20%",
                    "Reprice the five deepest-discount sub-categories",
                    "Track realised margin weekly for 90 days",
                ],
            )
        )

    losers = stats.get("loss_makers") or []
    if losers:
        loss = sum(abs(float(item.get("profit", 0))) for item in losers)
        names = ", ".join(item["name"] for item in losers[:3])
        plays.append(
            _play(
                "reprice-loss-makers",
                f"Reprice or exit {len(losers)} loss-making sub-categories",
                "These lines sell volume but destroy profit. Re-cost them, raise the floor price, "
                "or retire the SKUs where no viable price exists.",
                "Profitability",
                loss * 0.6,
                "profit",
                0.74,
                "medium",
                "12 months",
                [
                    f"{names} lost {_money(loss)} between them over the last 12 months.",
                    "Recovering 60% of the loss is assumed through repricing or exit.",
                ],
                [
                    "Recalculate unit economics per SKU",
                    "Apply a minimum-margin floor before any further discount",
                    "Archive SKUs that remain unprofitable after repricing",
                ],
            )
        )

    champions = stats.get("champions") or {}
    if champions.get("revenue", 0) > 0:
        plays.append(
            _play(
                "expand-champions",
                f"Grow wallet share of {champions.get('count', 0):,} Champions",
                "Your best customers already buy often. Bundle adjacent categories and add a "
                "premium tier instead of discounting the products they would buy anyway.",
                "Growth",
                champions["revenue"] * 0.08,
                "revenue",
                0.66,
                "low",
                "12 months",
                [
                    f"Champions generate {champions.get('revenue_share', 0):.1f}% of trailing-12-month "
                    f"revenue (≈{_money(champions.get('revenue', 0))}) from "
                    f"{champions.get('count', 0):,} customers.",
                    f"Average lifetime spend {_money(champions.get('avg_monetary', 0))} per customer.",
                    "8% wallet-share expansion assumed via cross-sell.",
                ],
                [
                    "Bundle the top two adjacent sub-categories",
                    "Launch early access for new product lines",
                    "Assign a named contact above $20k lifetime spend",
                ],
            )
        )

    concentration = stats.get("concentration") or {}
    if concentration.get("top10_share", 0) >= 20:
        plays.append(
            _play(
                "protect-key-accounts",
                "Protect revenue concentration",
                "A small group of accounts carries a large share of revenue. Formalise account "
                "plans and service levels so a single loss does not move the top line.",
                "Risk",
                concentration.get("top10_revenue", 0) * 0.05,
                "revenue",
                0.6,
                "medium",
                "12 months",
                [
                    f"Top 10 customers generate {concentration.get('top10_share', 0):.1f}% of "
                    f"trailing-12-month revenue ({_money(concentration.get('top10_revenue', 0))}).",
                    "5% of that revenue is assumed protected by account planning.",
                ],
                [
                    "Build account plans for the top 10",
                    "Review contract renewal dates for the next 12 months",
                    "Track concentration monthly against a 25% ceiling",
                ],
            )
        )

    acquisition = stats.get("acquisition") or {}
    if acquisition.get("new_customers", 0) > 0:
        plays.append(
            _play(
                "activate-new-customers",
                f"Convert {acquisition.get('new_customers', 0):,} new customers into repeat buyers",
                "Customers acquired in the last 90 days have not settled into a buying rhythm yet. "
                "A second-order incentive is the cheapest revenue available.",
                "Retention",
                acquisition.get("new_revenue", 0) * 0.12,
                "revenue",
                0.64,
                "low",
                "45 days",
                [
                    f"{acquisition.get('new_customers', 0):,} new customers spent "
                    f"{_money(acquisition.get('new_revenue', 0))} in the last 90 days.",
                    f"Repeat purchase rate across the base is {stats.get('repeat_rate', 0):.1f}%.",
                    "12% conversion to a second order is assumed.",
                ],
                [
                    "Trigger a second-order offer 14 days after first purchase",
                    "Recommend products from the same category",
                    "Measure 90-day repeat rate by cohort",
                ],
            )
        )

    review_rules = stats.get("rules_needing_review", 0)
    if review_rules:
        plays.append(
            _play(
                "review-bpr-rules",
                f"Review {review_rules} business rule{'s' if review_rules != 1 else ''} flagged for review",
                "Rules whose measured effectiveness has decayed should be rewritten or retired; "
                "keeping them active adds process cost without protecting margin.",
                "Operations",
                0.0,
                "efficiency",
                0.7,
                "low",
                "14 days",
                [
                    f"{review_rules} of {stats.get('rules_total', 0)} rules marked Needs Review.",
                    f"{stats.get('rules_triggering', 0)} rules triggered in the latest month.",
                ],
                [
                    "Open Data Drift & BPR and sort by effectiveness",
                    "Retire rules that no longer trigger on real conditions",
                    "Re-baseline thresholds against the last 12 months",
                ],
            )
        )

    # Drop immaterial opportunities so the page stays actionable; operational
    # hygiene plays (no dollar impact) are always kept.
    plays = [
        play for play in plays
        if play["impact_value"] >= 1_000 or play["impact_type"] == "efficiency"
    ]
    plays.sort(key=lambda item: (item["priority"], -item["impact_value"]))
    return plays[:6]


# ── Gemini ───────────────────────────────────────────────────────────────────
def build_strategy_prompt(
    kpis: List[Dict],
    segments: List[Dict],
    drift_alerts: List[Dict],
    plays: Optional[List[Dict]] = None,
) -> str:
    kpi_summary = "\n".join(
        f"- {k['kpi_name']}: {k['current_value']} {k['unit']} (target {k['target_value']}, drift {k['drift_score']:.2f})"
        for k in kpis
    )
    segment_summary = "\n".join(
        f"- {s['name']}: {s['count']} customers, {s.get('revenue_share', 0)}% of revenue, "
        f"avg spend ${s['avg_monetary']:.0f}"
        for s in segments
    )
    drift_summary = "\n".join(
        f"- {d['kpi']}: {d['status']} (PSI {d.get('psi')}, ADWIN score {d['drift_score']})"
        for d in drift_alerts
    )
    play_summary = "\n".join(
        f"- [{p['priority']}] {p['title']} — {p['impact_label']}, confidence {p['confidence']:.0%}. "
        f"{p['description']}"
        for p in (plays or [])
    )

    return f"""You are BIDS (Business Intelligence Decision System), a senior commercial analyst.

Prioritise the measured opportunities below into exactly 4 strategic recommendations.
Use only the numbers provided; do not invent metrics. Each item must be JSON with:
title, description, impact, risk_level (low/medium/high), confidence (0-1), category, priority (P1/P2/P3), actions (array of 3 short strings).

Current KPIs:
{kpi_summary}

Customer segments:
{segment_summary}

Drift signals:
{drift_summary if drift_summary else "No significant drift detected"}

Measured opportunities:
{play_summary if play_summary else "None computed"}

Respond ONLY with a valid JSON array. No markdown, no extra text."""


def _extract_json_from_text(text: str) -> str:
    text = text.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()
    bracket_start = text.find("[")
    if bracket_start != -1:
        return text[bracket_start:]
    return text


def get_gemini_recommendations(
    kpis: List[Dict],
    segments: List[Dict],
    drift_alerts: List[Dict],
    plays: Optional[List[Dict]] = None,
) -> Optional[List[Dict]]:
    """Return Gemini recommendations, or ``None`` when the API is unavailable."""
    if not GEMINI_API_KEY:
        return None

    try:
        import google.generativeai as genai

        genai.configure(api_key=GEMINI_API_KEY)
        prompt = build_strategy_prompt(kpis, segments, drift_alerts, plays)
        response = None
        for model_name in ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"):
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                if response and response.text:
                    break
            except Exception:
                continue

        if not response or not response.text:
            return None

        recommendations = json.loads(_extract_json_from_text(response.text))
        if not isinstance(recommendations, list) or not recommendations:
            return None

        cleaned: List[Dict] = []
        for item in recommendations[:4]:
            if not isinstance(item, dict):
                continue
            cleaned.append(
                {
                    "title": str(item.get("title", "Recommendation")),
                    "description": str(item.get("description", "")),
                    "impact": str(item.get("impact", "")),
                    "risk_level": str(item.get("risk_level", "medium")).lower(),
                    "confidence": float(item.get("confidence", 0.65) or 0.65),
                    "category": str(item.get("category", "Strategy")),
                    "priority": str(item.get("priority", "P2")),
                    "actions": [str(action) for action in item.get("actions", [])][:3],
                    "source": "gemini",
                }
            )
        return cleaned or None

    except Exception as exc:  # pragma: no cover - network / parsing failures
        print(f"Gemini strategy unavailable: {exc}")
        return None


def recommendations_from_plays(plays: List[Dict]) -> List[Dict]:
    """Map measured plays onto the recommendation shape the UI renders."""
    return [
        {
            "title": play["title"],
            "description": play["description"],
            "impact": play["impact_label"],
            "risk_level": play["risk_level"],
            "confidence": play["confidence"],
            "category": play["category"],
            "priority": play["priority"],
            "actions": play["actions"],
            "evidence": play["evidence"],
            "impact_value": play["impact_value"],
            "source": "measured",
        }
        for play in plays
    ]
