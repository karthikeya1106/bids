"""Lever optimiser: the recommendation must be reproducible in the simulator.

The optimiser is a grid search over the same simulator the what-if panel uses,
so every test here replays the recommended levers through ``/whatif`` and checks
the numbers agree. Refusals and the revenue floor are covered too.
"""
from __future__ import annotations

import json

import pytest

from tests import data
from tests.conftest import csv_bytes

HORIZON = 6
SPEND = 5_000.0


def _upload(client, headers, frame, filename="sales.csv"):
    preview = client.post(
        "/api/upload/preview?analysis_type=auto",
        files={"file": (filename, csv_bytes(frame), "text/csv")},
        headers=headers,
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    mapping = {key: value["value"] for key, value in body["mapping"].items() if value.get("value")}
    commit = client.post(
        "/api/upload/commit",
        files={"file": (filename, csv_bytes(frame), "text/csv")},
        data={
            "schema": body["analysis_type"],
            "mapping": json.dumps(mapping),
            "task": body["task"],
            "target": body["target"] or "",
            "org_name": "Optimiser Test",
        },
        headers=headers,
    )
    assert commit.status_code == 200, commit.text
    return commit.json()


def _optimise(client, headers, **body):
    response = client.post(
        "/api/forecast/optimize",
        json={"horizon_months": HORIZON, "marketing_spend": SPEND, **body},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_best_combination_replays_in_the_simulator(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.sales_with_elastic_demand(400))

    result = _optimise(client, headers)
    assert result["has_data"] is True
    best = result["best"]
    assert best is not None

    replay = client.post(
        "/api/forecast/whatif",
        json={
            "price_change": best["price_change"],
            "discount_change": best["discount_change"],
            "marketing_boost": best["marketing_boost"],
            "horizon_months": HORIZON,
            "marketing_spend": SPEND,
        },
        headers=headers,
    ).json()

    assert replay["adjusted_profit"] == pytest.approx(best["profit"], rel=1e-9)
    assert replay["profit_impact"] == pytest.approx(best["profit_impact"], rel=1e-9)
    assert replay["impact_pct"] == pytest.approx(best["revenue_impact_pct"], rel=1e-9)
    assert replay["marketing_spend"]["incremental"] == pytest.approx(best["incremental_marketing_spend"], rel=1e-9)


def test_doing_nothing_is_in_the_grid_so_the_best_is_never_worse(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.sales_with_elastic_demand(400))
    result = _optimise(client, headers)

    assert result["best"]["profit_impact"] >= -1e-6
    assert result["search"]["combinations"] == len(result["tradeoff"])
    # The recommendation is the most profitable evaluated point.
    assert result["best"]["profit_impact"] == max(row["profit_impact"] for row in result["tradeoff"])
    assert result["baseline"]["revenue"] > 0
    assert result["baseline"]["profit"] > 0


def test_search_respects_the_requested_ranges(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.sales_with_elastic_demand(400))
    result = _optimise(client, headers, max_price_change=5, max_marketing_boost=10, max_discount_cut=10)

    assert result["search"]["price_change"][0] == pytest.approx(-5)
    assert result["search"]["price_change"][-1] == pytest.approx(5)
    assert all(-5 - 1e-9 <= row["price_change"] <= 5 + 1e-9 for row in result["tradeoff"])
    assert all(row["marketing_boost"] <= 10 + 1e-9 for row in result["tradeoff"])


def test_revenue_floor_rejects_profit_that_shrinks_the_business(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.sales_with_elastic_demand(400))

    unconstrained = _optimise(client, headers)
    constrained = _optimise(client, headers, min_revenue_impact_pct=-1.0)

    assert constrained["constraint"] == {"min_revenue_impact_pct": -1.0}
    if constrained["best"] is not None:
        assert constrained["best"]["revenue_impact_pct"] >= -1.0 - 1e-9
        assert constrained["best"]["profit_impact"] <= unconstrained["best"]["profit_impact"] + 1e-9
        assert constrained["best_unconstrained"] is not None


def test_optimiser_explains_its_search_and_elasticity(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.sales_with_elastic_demand(400))
    result = _optimise(client, headers)

    assert result["objective"] == "net profit over the horizon"
    assert result["elasticity"]["measured"] is True
    assert result["assumptions"]["incremental_marketing_spend"] >= 0
    assert any("grid point" in note for note in result["notes"])
    assert any("Evaluated" in note for note in result["notes"])


def test_assumed_elasticity_is_called_out_as_indicative(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.sales_standard(240))
    result = _optimise(client, headers)

    assert result["elasticity"]["measured"] is False
    assert any("assumed prior" in note for note in result["notes"])


def test_non_sales_dataset_is_refused(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.telecom_churn(200), filename="churn.csv")
    response = client.post("/api/forecast/optimize", json={"horizon_months": HORIZON}, headers=headers)
    assert response.status_code == 400
    assert "sales timeline" in response.json()["detail"]


def test_optimiser_requires_a_signature(client):
    response = client.post("/api/forecast/optimize", json={"horizon_months": HORIZON})
    assert response.status_code == 401
