"""Tests for the dataset capability registry and the six adaptive modules."""
from __future__ import annotations

import json

from tests import data
from tests.conftest import csv_bytes


def _preview(client, headers, frame, name="dataset.csv", analysis_type="auto"):
    response = client.post(
        f"/api/upload/preview?analysis_type={analysis_type}",
        files={"file": (name, csv_bytes(frame), "text/csv")},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _upload(client, headers, frame, name="dataset.csv", analysis_type="auto"):
    preview = _preview(client, headers, frame, name, analysis_type)
    mapping = {
        key: decision["value"]
        for key, decision in preview["mapping"].items()
        if decision.get("value")
    }
    response = client.post(
        "/api/upload/commit",
        files={"file": (name, csv_bytes(frame), "text/csv")},
        data={
            "schema": preview["analysis_type"],
            "mapping": json.dumps(mapping),
            "task": preview["task"],
            "target": preview["target"] or "",
            "org_name": "Test Org",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return preview, response.json()


def _active_dataset_id(client, headers) -> int:
    status = client.get("/api/upload/status", headers=headers)
    assert status.status_code == 200
    return status.json()["dataset"]["id"]


def test_subscription_export_is_recognised_as_a_churn_dataset(client, auth, owner):
    headers = auth(owner)
    frame = data.subscription_churn(400)
    preview = _preview(client, headers, frame, name="internet_service_churn.csv")

    assert preview["analysis_type"] == "churn"
    assert preview["mapping"]["churn_status"]["column"] == "churn"
    # The subscription columns must not land on sales/order fields.
    for key in ("sales", "order_date", "order_id"):
        decision = preview["mapping"].get(key)
        assert not decision or decision.get("column") is None
    suggested = [target["column"] for target in preview["targets"]]
    assert "churn" in suggested

    _, committed = _upload(client, headers, frame, name="internet_service_churn.csv")
    assert committed["schema"] == "churn"

    report = client.get("/api/analysis/report", headers=headers).json()
    assert report["mode"] == "adaptive"
    capabilities = report["capabilities"]
    # A mapped churn dataset stores the canonical label column; a generic one
    # keeps the source name. Both must be recognised as the outcome.
    assert capabilities["target"]["column"] in {"churn", "churn_status"}
    if capabilities["target"]["confirmed"]:
        assert report["target_suggestion"] is None
    else:
        assert report["target_suggestion"] is not None
    assert capabilities["modules"]["dashboard"]["status"] == "ready"
    assert capabilities["modules"]["forecast"]["status"] in {"ready", "partial"}
    assert capabilities["modules"]["drift"]["status"] == "partial"


def test_every_module_uses_the_active_churn_dataset(client, auth, owner):
    headers = auth(owner)
    frame = data.subscription_churn(700)
    # Store it as a general dataset, exactly like an upload that did not match a
    # domain template. Capabilities must still come from the data itself.
    _upload(client, headers, frame, name="internet_service_churn.csv", analysis_type="generic")

    status = client.get("/api/upload/status", headers=headers).json()
    assert status["schema"] == "generic"
    dataset_id = status["dataset"]["id"]

    responses = {}
    for module, endpoint in (
        ("dashboard", "/api/dashboard"),
        ("behavior", "/api/behavior"),
        ("segmentation", "/api/segments"),
        ("rootcause", "/api/rootcause"),
        ("drift", "/api/drift"),
        ("forecast", "/api/forecast"),
        ("strategy", "/api/strategy/insights"),
    ):
        response = client.get(endpoint, headers=headers)
        assert response.status_code == 200, f"{module}: {response.text}"
        body = response.json()
        assert body["mode"] == "adaptive", module
        assert body["dataset"]["id"] == dataset_id
        assert "sales transaction history" not in json.dumps(body)
        assert body["status"] in {"ready", "partial", "unavailable"}
        responses[module] = body

    # ── Dashboard values against an independent computation ────────────────
    dashboard = responses["dashboard"]
    assert dashboard["status"] == "ready"
    expected_rate = float(frame["churn"].mean() * 100)
    labels = {card["label"]: card for card in dashboard["summary"]}
    churn_card = labels.get("Churn rate")
    assert churn_card is not None
    assert abs(float(churn_card["value"]) - expected_rate) < 0.01
    assert "Revenue" not in " ".join(labels)

    measures_rows = next(
        section for section in dashboard["sections"] if section["id"] == "measures-by-outcome"
    )["rows"]
    download_row = next(row for row in measures_rows if row["factor"] == "Download Avg")
    expected_download = float(frame.loc[frame["churn"] == 1, "download_avg"].mean())
    assert abs(float(download_row["event_mean"]) - expected_download) < 0.05

    # ── Behaviour ──────────────────────────────────────────────────────────
    behavior = responses["behavior"]
    assert behavior["status"] == "ready"
    assert any(section["id"] == "numeric-association" for section in behavior["sections"])

    # ── Segmentation ───────────────────────────────────────────────────────
    segmentation = responses["segmentation"]
    assert segmentation["status"] == "ready"
    profile_table = next(section for section in segmentation["sections"] if section["id"] == "segment-profiles")
    assert len(profile_table["rows"]) >= 2
    for row in profile_table["rows"]:
        assert 0 <= float(row["outcome_rate"]) <= 100

    # ── Root cause ─────────────────────────────────────────────────────────
    rootcause = responses["rootcause"]
    assert rootcause["status"] == "ready"
    evidence = next(section for section in rootcause["sections"] if section["id"] == "driver-evidence")
    assert evidence["rows"]
    # The outcome must never be tested as its own driver.
    assert all(row["factor"].lower() != "churn" for row in evidence["rows"])

    # ── Drift needs a real baseline ────────────────────────────────────────
    drift = responses["drift"]
    assert drift["status"] == "partial"
    assert drift["requires"]
    assert all(section["id"] != "drift-detail" for section in drift["sections"])

    # ── Forecast needs a confirmed target here (no date column) ────────────
    forecast = responses["forecast"]
    assert forecast["status"] == "partial"
    assert any("target" in item.lower() for item in forecast["requires"])

    # ── Strategy is measured, not invented ─────────────────────────────────
    strategy = responses["strategy"]
    assert strategy["status"] == "ready"
    plays = next(section for section in strategy["sections"] if section["id"] == "plays")["rows"]
    assert plays
    baseline = expected_rate
    for play in plays:
        assert float(play["rate"]) > baseline
        assert int(play["excess_events"]) > 0
        assert play["confidence"] == "Association-based"


def test_confirming_the_target_enables_a_supervised_model(client, auth, owner):
    headers = auth(owner)
    frame = data.subscription_churn(700)
    _upload(client, headers, frame, name="churn.csv", analysis_type="generic")
    dataset_id = _active_dataset_id(client, headers)

    before = client.get("/api/forecast", headers=headers).json()
    assert before["status"] == "partial"

    response = client.patch(
        f"/api/datasets/{dataset_id}/target",
        json={"target": "churn"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["target"]["confirmed"] is True
    assert body["target"]["column"] == "churn"

    forecast = client.get("/api/forecast", headers=headers).json()
    assert forecast["status"] == "ready"
    assert forecast["summary"]
    confusion = next(section for section in forecast["sections"] if section["id"] == "confusion")
    assert len(confusion["matrix"]) == 2
    assert any(section["id"] == "importances" for section in forecast["sections"])
    assert any(section["id"] == "risk-bands" for section in forecast["sections"])
    for card in forecast["summary"]:
        if card["label"] in {"Accuracy (holdout)", "Balanced accuracy"}:
            assert 0 <= float(card["value"]) <= 100

    report = client.get("/api/analysis/report", headers=headers).json()
    task = report["adaptive"]["task"]
    assert task["type"] == "classification"
    assert task["metrics"]["accuracy"] is not None
    assert report["capabilities"]["target"]["confirmed"] is True
    assert report["target_suggestion"] is None

    # Clearing the target returns the dataset to descriptive analysis.
    cleared = client.patch(
        f"/api/datasets/{dataset_id}/target", json={"target": None}, headers=headers
    )
    assert cleared.status_code == 200
    assert cleared.json()["target"]["confirmed"] is False
    assert client.get("/api/forecast", headers=headers).json()["status"] == "partial"


def test_target_validation_rejects_bad_columns(client, auth, owner):
    headers = auth(owner)
    frame = data.subscription_churn(300)
    _upload(client, headers, frame, name="churn.csv", analysis_type="generic")
    dataset_id = _active_dataset_id(client, headers)

    assert client.patch(
        f"/api/datasets/{dataset_id}/target", json={"target": "not_a_column"}, headers=headers
    ).status_code == 422
    assert client.patch(
        f"/api/datasets/{dataset_id}/target",
        json={"target": "churn", "task": "clustering"},
        headers=headers,
    ).status_code == 422
    assert client.patch(
        f"/api/datasets/{dataset_id}/target",
        json={"target": "download_avg", "task": "classification"},
        headers=headers,
    ).status_code == 422


def test_drift_compares_two_reference_datasets(client, auth, owner):
    headers = auth(owner)
    baseline = data.subscription_churn(600, shifted=False)
    _upload(client, headers, baseline, name="baseline.csv", analysis_type="generic")
    baseline_id = _active_dataset_id(client, headers)

    current = data.subscription_churn(600, shifted=True)
    _upload(client, headers, current, name="current.csv", analysis_type="generic")

    response = client.get(f"/api/drift?reference_id={baseline_id}", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["reference"]["mode"] == "reference"
    detail = next(section for section in payload["sections"] if section["id"] == "drift-detail")
    assert detail["rows"]
    assert any(row["status"] in {"shifted", "watch"} for row in detail["rows"])
    for row in detail["rows"]:
        assert 0 <= float(row["psi"]) <= 10


def test_time_series_dataset_forecasts_and_compares_periods(client, auth, owner):
    headers = auth(owner)
    frame = data.monthly_timeseries(40)
    _upload(client, headers, frame, name="monthly.csv", analysis_type="generic")

    forecast = client.get("/api/forecast", headers=headers).json()
    assert forecast["mode"] == "adaptive"
    assert forecast["status"] == "ready"
    assert any(section["kind"] == "line" for section in forecast["sections"])

    drift = client.get("/api/drift", headers=headers).json()
    assert drift["status"] == "ready"
    assert drift["reference"]["mode"] == "time"

    rootcause = client.get("/api/rootcause", headers=headers).json()
    assert rootcause["status"] == "ready"
    assert rootcause["sections"]
    assert any(section["id"] in {"period-change", "no-outcome"} for section in rootcause["sections"])


def test_capabilities_are_scoped_to_the_dataset_owner(client, auth, owner):
    frame = data.subscription_churn(200)
    _upload(client, auth(owner), frame, name="private.csv", analysis_type="generic")
    dataset_id = _active_dataset_id(client, auth(owner))

    other = auth(f"other-{owner}")
    assert client.get("/api/datasets/active/capabilities", headers=other).status_code == 404

    dashboard = client.get("/api/dashboard", headers=other).json()
    assert dashboard["has_data"] is False

    assert client.patch(
        f"/api/datasets/{dataset_id}/target", json={"target": "churn"}, headers=other
    ).status_code == 404
    assert client.get("/api/analysis/report", headers=other).status_code == 404


def test_sales_dataset_keeps_the_sales_dashboard(client, auth, owner):
    headers = auth(owner)
    _upload(client, headers, data.sales_standard(150))

    dashboard = client.get("/api/dashboard", headers=headers).json()
    assert dashboard.get("mode") != "adaptive"
    assert dashboard["has_data"] is True
    assert dashboard["kpis"]
    assert dashboard["revenue_trend"]

    report = client.get("/api/analysis/report", headers=headers).json()
    assert report["mode"] == "sales"


def test_dataset_without_an_outcome_is_not_given_fake_kpis(client, auth, owner):
    headers = auth(owner)
    frame = data.categorical_only(90)
    _upload(client, headers, frame, name="segments.csv", analysis_type="generic")

    dashboard = client.get("/api/dashboard", headers=headers).json()
    labels = [card["label"] for card in dashboard["summary"]]
    assert "Churn rate" not in labels
    assert "Revenue" not in labels
    assert any("No outcome" in json.dumps(section) for section in dashboard["sections"])

    forecast = client.get("/api/forecast", headers=headers).json()
    assert forecast["status"] == "unavailable"
    assert forecast["requires"]
