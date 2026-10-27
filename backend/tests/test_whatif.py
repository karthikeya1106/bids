"""What-if simulator: elasticity provenance, marketing cost and refusals.

The simulator scales every number by a price elasticity. These tests pin down
that it says where that elasticity came from, that an assumed one is never
presented as measured, that a marketing boost is charged to profit when a spend
baseline is supplied, and that it refuses datasets without a sales timeline.
"""
from __future__ import annotations

import json

from tests import data
from tests.conftest import csv_bytes


def _upload(client, headers, frame):
    preview = client.post(
        "/api/upload/preview?analysis_type=auto",
        files={"file": ("sales.csv", csv_bytes(frame), "text/csv")},
        headers=headers,
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    mapping = {key: value["value"] for key, value in body["mapping"].items() if value.get("value")}
    commit = client.post(
        "/api/upload/commit",
        files={"file": ("sales.csv", csv_bytes(frame), "text/csv")},
        data={
            "schema": body["analysis_type"],
            "mapping": json.dumps(mapping),
            "task": body["task"],
            "target": body["target"] or "",
            "org_name": "Simulator Test",
        },
        headers=headers,
    )
    assert commit.status_code == 200, commit.text
    return commit.json()


def _whatif(client, headers, **body):
    response = client.post("/api/forecast/whatif", json={"horizon_months": 6, **body}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ─── Elasticity provenance ───────────────────────────────────────────────────

def test_elasticity_is_measured_when_orders_show_price_response(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.sales_with_elastic_demand(400))

    forecast = client.get("/api/forecast?horizon=6", headers=headers).json()
    elasticity = forecast["elasticity"]

    assert elasticity["measured"] is True
    assert elasticity["method"].startswith("OLS")
    assert elasticity["sample"] >= 60
    assert elasticity["r2"] is not None and elasticity["r2"] > 0.2
    # The fixture was generated with a true slope of -1.6.
    assert -2.4 <= elasticity["value"] <= -0.9
    low, high = elasticity["band"]
    assert low <= elasticity["value"] <= high
    assert elasticity["stderr"] is not None

    defaults = forecast["defaults"]
    assert defaults["elasticity_measured"] is True
    assert defaults["price_elasticity"] == elasticity["value"]
    assert defaults["elasticity_band"] == elasticity["band"]


def test_elasticity_is_labelled_assumed_when_it_cannot_be_estimated(client, auth, owner):
    headers = auth(owner)
    # Quantity is drawn independently of price here, so no demand curve exists.
    _upload(client, headers, data.sales_standard(240))

    forecast = client.get("/api/forecast?horizon=6", headers=headers).json()
    elasticity = forecast["elasticity"]

    assert elasticity["measured"] is False
    assert elasticity["method"] == "prior"
    assert elasticity["reason"]
    assert elasticity["sample"] >= 60  # enough lines: rejected on the fit, not the count
    assert elasticity["band"] == [-2.0, -0.6]
    assert forecast["defaults"]["elasticity_measured"] is False
    assert forecast["defaults"]["elasticity_reason"] == elasticity["reason"]
    assert forecast["defaults"]["elasticity_band"] == [-2.0, -0.6]


def test_whatif_reports_the_elasticity_it_used(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.sales_with_elastic_demand(400))

    result = _whatif(client, headers, price_change=5)

    assert result["elasticity"]["measured"] is True
    assert result["elasticity"]["overridden_for_sensitivity"] is False
    assert result["assumptions"]["elasticity_measured"] is True
    assert result["assumptions"]["price_elasticity"] == result["elasticity"]["value_used"]
    assert result["assumptions"]["elasticity_sample"] >= 60


# ─── Marketing spend ─────────────────────────────────────────────────────────

def test_marketing_spend_is_charged_to_profit_when_a_baseline_is_given(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.sales_with_elastic_demand(300))

    without = _whatif(client, headers, marketing_boost=50)
    with_spend = _whatif(client, headers, marketing_boost=50, marketing_spend=4000)

    # Revenue is identical: the boost lifts volume either way.
    assert with_spend["adjusted_total"] == without["adjusted_total"]
    assert with_spend["impact_pct"] == without["impact_pct"]
    # Profit differs by exactly the incremental spend (50% of 4,000).
    assert with_spend["marketing_spend"]["basis"] == 4000
    assert with_spend["marketing_spend"]["incremental"] == 2000
    assert with_spend["marketing_spend"]["charged"] is True
    assert abs((without["profit_impact"] - with_spend["profit_impact"]) - 2000) < 0.01
    assert with_spend["assumptions"]["marketing_spend_not_deducted"] is False
    assert without["assumptions"]["marketing_spend_not_deducted"] is True


def test_marketing_spend_is_not_charged_without_a_boost(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.sales_with_elastic_demand(300))

    result = _whatif(client, headers, price_change=3, marketing_spend=4000)

    assert result["marketing_spend"]["incremental"] == 0
    assert result["marketing_spend"]["charged"] is False
    assert result["assumptions"]["marketing_spend_not_deducted"] is False


# ─── Arithmetic ──────────────────────────────────────────────────────────────

def test_breakdown_reconciles_with_the_total(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.sales_with_elastic_demand(320))

    for scenario in (
        {"price_change": 10},
        {"discount_change": -20},
        {"marketing_boost": 40, "marketing_spend": 2500},
        {"price_change": 6, "discount_change": -10, "marketing_boost": 25, "marketing_spend": 1000},
    ):
        result = _whatif(client, headers, **scenario)
        delta = result["adjusted_total"] - result["base_total"]
        assert abs(delta - sum(result["breakdown"].values())) < 0.05, scenario
        assert abs(result["impact_pct"] - delta / result["base_total"] * 100) < 0.01


def test_price_rise_reduces_revenue_when_demand_is_elastic(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.sales_with_elastic_demand(400))

    result = _whatif(client, headers, price_change=10)

    assert result["assumptions"]["price_elasticity"] < -1.0
    assert result["adjusted_total"] < result["base_total"]
    assert result["impact_pct"] < 0


# ─── Refusals ────────────────────────────────────────────────────────────────

def test_whatif_refuses_a_dataset_without_a_sales_timeline(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.telecom_churn(200))

    response = client.post(
        "/api/forecast/whatif",
        json={"price_change": 5, "horizon_months": 6},
        headers=headers,
    )
    assert response.status_code == 400
    assert "sales" in response.json()["detail"]


def test_whatif_requires_a_signed_identity(client):
    response = client.post("/api/forecast/whatif", json={"price_change": 5})
    assert response.status_code == 401


def test_whatif_rejects_impossible_inputs(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.sales_with_elastic_demand(200))

    assert client.post(
        "/api/forecast/whatif", json={"price_change": 500}, headers=headers
    ).status_code == 422
    assert client.post(
        "/api/forecast/whatif", json={"marketing_spend": -1}, headers=headers
    ).status_code == 422
    assert client.post(
        "/api/forecast/whatif", json={"horizon_months": 99}, headers=headers
    ).status_code == 422
