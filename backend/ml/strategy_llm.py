"""
Strategy Recommendation Engine using Google Gemini API.
Falls back to rule-based recommendations if API key is unavailable.
"""
import os
import re
import json
from typing import Dict, List
from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def build_strategy_prompt(kpis: List[Dict], segments: List[Dict], drift_alerts: List[Dict]) -> str:
    kpi_summary = "\n".join([
        f"- {k['kpi_name']}: {k['current_value']} {k['unit']} (target: {k['target_value']}, drift: {k['drift_score']:.0%})"
        for k in kpis
    ])
    segment_summary = "\n".join([
        f"- {s['name']}: {s['count']} customers (avg spend: ${s['avg_monetary']:.0f})"
        for s in segments
    ])
    drift_summary = "\n".join([f"- {d['kpi']} drift detected" for d in drift_alerts if d.get("drift_detected")])

    return f"""You are BIDS (Business Intelligence Decision System), an expert business analyst AI.

Based on the following business metrics, provide exactly 4 strategic recommendations.
Each recommendation must be actionable, specific, and data-driven.
Format as a JSON array with fields: title, description, impact, risk_level (low/medium/high), confidence (0-1), category.

Current KPIs:
{kpi_summary}

Customer Segments:
{segment_summary}

Data Drift Alerts:
{drift_summary if drift_summary else "No significant drift detected"}

Respond ONLY with valid JSON array. No markdown, no explanation outside JSON."""


def _extract_json_from_text(text: str) -> str:
    """
    Robustly extract a JSON array from a response that may contain markdown fences.
    Handles: ```json ... ```, ``` ... ```, or raw JSON.
    """
    text = text.strip()

    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()

    # If starts with a JSON array bracket, use it directly
    bracket_start = text.find("[")
    if bracket_start != -1:
        return text[bracket_start:]

    return text


def get_gemini_recommendations(kpis: List[Dict], segments: List[Dict], drift_alerts: List[Dict]) -> List[Dict]:
    if not GEMINI_API_KEY:
        return _rule_based_recommendations(kpis, segments)

    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)

        # Try supported flash models in order of capability
        candidate_models = ["gemini-3.8-flash", "gemini-flash-latest", "gemini-2.5-flash-lite", "gemini-1.5-flash"]
        prompt = build_strategy_prompt(kpis, segments, drift_alerts)
        response = None
        for model_name in candidate_models:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                if response and response.text:
                    break
            except Exception:
                continue

        if not response or not response.text:
            return _rule_based_recommendations(kpis, segments)

        raw = response.text
        cleaned = _extract_json_from_text(raw)
        recommendations = json.loads(cleaned)

        if not isinstance(recommendations, list):
            raise ValueError("Gemini response is not a JSON array")

        return recommendations[:4]

    except json.JSONDecodeError as e:
        print(f"Gemini JSON parse error: {e}. Falling back to rule-based.")
        return _rule_based_recommendations(kpis, segments)
    except Exception as e:
        print(f"Gemini API error: {e}. Falling back to rule-based.")
        return _rule_based_recommendations(kpis, segments)


def _rule_based_recommendations(kpis: List[Dict], segments: List[Dict]) -> List[Dict]:
    """Fallback rule-based strategy generation."""
    recs = []

    # Find high drift KPIs
    high_drift = [k for k in kpis if k.get("drift_score", 0) > 0.3]

    # Retention recommendation
    retention_kpi = next((k for k in kpis if "Retention" in k.get("kpi_name", "")), None)
    if retention_kpi and retention_kpi.get("current_value", 100) < retention_kpi.get("target_value", 100):
        gap = retention_kpi["target_value"] - retention_kpi["current_value"]
        recs.append({
            "title": "Launch Retention Recovery Program",
            "description": f"Customer retention is {retention_kpi['current_value']}% vs target {retention_kpi['target_value']}%. Deploy personalized re-engagement campaigns for At-Risk and Lost segments with targeted 20% discount offers.",
            "impact": f"+{gap:.1f}% retention rate improvement projected over 90 days",
            "risk_level": "low",
            "confidence": 0.82,
            "category": "Retention",
        })

    # Segment-specific recommendation
    at_risk = next((s for s in segments if s.get("name") == "At-Risk"), None)
    if at_risk and at_risk.get("count", 0) > 50:
        recs.append({
            "title": f"Activate {at_risk['count']} At-Risk Customers",
            "description": "High volume of at-risk customers detected. Implement a 3-touch re-engagement sequence: email → SMS → personalized offer. Focus on their historically purchased sub-categories.",
            "impact": "Projected 15-22% win-back rate → $" + str(round(at_risk["avg_monetary"] * at_risk["count"] * 0.18, 0))[:-2] + "K potential recovery",
            "risk_level": "low",
            "confidence": 0.76,
            "category": "Revenue Recovery",
        })

    # Pricing recommendation
    margin_kpi = next((k for k in kpis if "Margin" in k.get("kpi_name", "")), None)
    if margin_kpi and margin_kpi.get("current_value", 20) < 15:
        recs.append({
            "title": "Optimize Discount Strategy",
            "description": "Profit margins below 15% indicate excessive discounting. Introduce dynamic pricing — cap discounts at 15% for Technology category, maintain 20% cap for Furniture clearance only.",
            "impact": "+2-4% profit margin improvement within 60 days",
            "risk_level": "medium",
            "confidence": 0.71,
            "category": "Pricing",
        })

    # Champions loyalty recommendation
    champions = next((s for s in segments if s.get("name") == "Champions"), None)
    if champions:
        recs.append({
            "title": "Champions Loyalty Acceleration",
            "description": f"Your {champions.get('count', 0)} Champion customers average ${champions.get('avg_monetary', 0):.0f} spend. Launch exclusive early access and premium loyalty tier to increase wallet share by 25%.",
            "impact": f"${round(champions.get('count', 0) * champions.get('avg_monetary', 0) * 0.25 / 1000, 1)}K additional revenue from top-tier segment",
            "risk_level": "low",
            "confidence": 0.88,
            "category": "Growth",
        })

    # Ensure we always have 4
    while len(recs) < 4:
        recs.append({
            "title": "Expand High-Margin Product Lines",
            "description": "Technology sub-categories (Phones, Accessories) show highest profit margins. Increase inventory allocation and targeted campaigns for these SKUs.",
            "impact": "+8-12% overall profit margin within one quarter",
            "risk_level": "medium",
            "confidence": 0.67,
            "category": "Operations",
        })

    return recs[:4]
