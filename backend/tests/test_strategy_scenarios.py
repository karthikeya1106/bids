"""Strategy plays as simulator scenarios.

Every play keeps its measured annual estimate, and the scenario answers a
different question: what the play's mechanism does to revenue and net profit over
the forecast horizon, with a range that reflects how uncertain the elasticity is.
These tests pin the contract the UI relies on — every play is accounted for, the
range brackets the central estimate, the numbers agree with the what-if endpoint,
marketing spend is charged, and non-sales datasets are refused.
"""
from __future__ import annotations

import json

from services.scenarios import PLAY_SCENARIOS

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
            "org_name": "Scenario Test",
        },
        headers=headers,
    )
    assert commit.status_code == 200, commit.text
    return commit.json()


def _insights(client, headers):
    response = client.get("/api/strategy/insights", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _scenarios(client, headers, **body):
    response = client.post(
        "/api/strategy/scenarios",
        json={"horizon_months": 6, **body},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_every_play_is_either_simulated_or_explained(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.sales_with_elastic_demand(400))

    insights = _insights(client, headers)
    simulated = _scenarios(client, headers)

    assert simulated["available"] is True
    play_ids = {play["id"] for play in insights["plays"]}
    assert play_ids, "the sales fixture should produce at least one measured play"
    assert set(simulated["plays"]) == play_ids

    for play_id, scenario in simulated["plays"].items():
        if scenario["available"]:
            assert set(scenario["levers"]) == {"price_change", "discount_change", "marketing_boost"}
            assert scenario["rationale"]
            assert scenario["horizon_months"] == 6
            assert scenario["base_revenue"] > 0
            assert scenario["revenue_impact"] == round(
                scenario["scenario_revenue"] - scenario["base_revenue"], 2
            )
            low, high = scenario["sensitivity"]["revenue_impact_range"]
            assert low - 0.01 <= scenario["revenue_impact"] <= high + 0.01
            low_profit, high_profit = scenario["sensitivity"]["profit_impact_range"]
            assert low_profit - 0.01 <= scenario["profit_impact"] <= high_profit + 0.01
            assert "elasticity_measured" in scenario["assumptions"]
        else:
            assert scenario["reason"]


def test_plays_without_a_price_lever_are_not_forced_into_one(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.sales_with_elastic_demand(400))

    simulated = _scenarios(client, headers)
    for play_id, scenario in simulated["plays"].items():
        if play_id in {"protect-key-accounts", "review-bpr-rules"}:
            assert scenario["available"] is False
            assert scenario["reason"]


def test_every_simulatable_play_uses_a_documented_lever_set(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.sales_with_elastic_demand(400))

    simulated = _scenarios(client, headers)
    for play_id, scenario in simulated["plays"].items():
        if scenario["available"]:
            assert scenario["levers"] == PLAY_SCENARIOS[play_id]["levers"]


def test_scenario_matches_the_whatif_endpoint_for_the_same_levers(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.sales_with_elastic_demand(400))

    simulated = _scenarios(client, headers, marketing_spend=3000)
    target = next(
        (scenario for scenario in simulated["plays"].values() if scenario["available"]),
        None,
    )
    assert target is not None

    direct = client.post(
        "/api/forecast/whatif",
        json={
            **target["levers"],
            "horizon_months": simulated["horizon_months"],
            "marketing_spend": 3000,
        },
        headers=headers,
    )
    assert direct.status_code == 200, direct.text
    direct = direct.json()

    assert direct["adjusted_total"] == target["scenario_revenue"]
    assert direct["profit_impact"] == target["profit_impact"]
    assert direct["base_total"] == target["base_revenue"]


def test_scenario_baseline_is_the_same_forecast_the_page_shows(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.sales_with_elastic_demand(400))

    forecast = client.get("/api/forecast?horizon=6", headers=headers).json()
    simulated = _scenarios(client, headers)

    forecast_total = round(sum(point["value"] for point in forecast["forecast"]), 2)
    assert simulated["simulation"]["baseline_revenue"] == forecast_total
    assert simulated["simulation"]["model"] == forecast["model"]
    assert simulated["simulation"]["elasticity"]["value"] == forecast["elasticity"]["value"]


def test_marketing_spend_is_charged_inside_play_scenarios(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.sales_with_elastic_demand(400))

    free = _scenarios(client, headers)
    charged = _scenarios(client, headers, marketing_spend=5000)

    boosted = [
        play_id for play_id, scenario in charged["plays"].items()
        if scenario.get("available") and scenario["levers"]["marketing_boost"] > 0
    ]
    assert boosted, "at least one play should carry a marketing lever"
    for play_id in boosted:
        boost = charged["plays"][play_id]["levers"]["marketing_boost"]
        assert charged["plays"][play_id]["marketing_cost"] == round(5000 * boost / 100, 2)
        assert charged["plays"][play_id]["profit_impact"] < free["plays"][play_id]["profit_impact"]
    assert charged["simulation"]["marketing_spend_charged"] is True
    assert free["simulation"]["marketing_spend_charged"] is False


def test_scenario_horizon_is_respected(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.sales_with_elastic_demand(400))

    simulated = _scenarios(client, headers, horizon_months=9)
    assert simulated["horizon_months"] == 9
    assert simulated["simulation"]["horizon_months"] == 9
    for scenario in simulated["plays"].values():
        if scenario["available"]:
            assert scenario["horizon_months"] == 9


def test_scenarios_refuse_a_dataset_without_a_sales_timeline(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.telecom_churn(200))

    response = client.post(
        "/api/strategy/scenarios",
        json={"horizon_months": 6},
        headers=headers,
    )
    assert response.status_code == 400
    assert "sales" in response.json()["detail"]


def test_scenarios_require_a_signed_identity(client):
    response = client.post("/api/strategy/scenarios", json={"horizon_months": 6})
    assert response.status_code == 401
