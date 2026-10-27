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


def _commit(client, headers, frame, preview, name="dataset.csv"):
    mapping = {
        key: decision["value"]
        for key, decision in preview["mapping"].items()
        if decision["value"]
    }
    return client.post(
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


def test_preview_exposes_classification_mapping_and_validation(client, auth, owner):
    frame = data.sales_standard(90)
    payload = _preview(client, auth(owner), frame)

    assert payload["analysis_type"] == "sales"
    assert payload["classification"]["confidence"] >= 60
    assert payload["profile"]["rows"] == 90
    assert payload["mapping"]["sales"]["column"] == "Sales"
    assert payload["mapping"]["sales"]["reasons"]
    assert payload["validation"]["ready"] is True
    assert payload["task"] == "forecast"
    assert payload["target"] == "sales"
    assert "forecast" in payload["tasks"]
    assert payload["modules"]["dashboard"] is True


def test_commit_ingests_sales_and_populates_modules(client, auth, owner):
    headers = auth(owner)
    frame = data.sales_standard(120)
    preview = _preview(client, headers, frame)
    response = _commit(client, headers, frame, preview)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rows_loaded"] == 120
    assert body["schema"] == "sales"

    status = client.get("/api/upload/status", headers=auth(owner)).json()
    assert status["has_data"] is True
    assert status["schema"] == "sales"
    assert status["modules"]["dashboard"] is True

    dashboard = client.get("/api/dashboard", headers=auth(owner))
    assert dashboard.status_code == 200
    assert dashboard.json()["has_data"] is True

    forecast = client.get("/api/forecast?horizon=6", headers=auth(owner))
    assert forecast.status_code == 200

    report = client.get("/api/analysis/report", headers=auth(owner))
    assert report.status_code == 200
    assert report.json()["mode"] == "sales"


def test_churn_dataset_is_never_presented_as_sales(client, auth, owner):
    headers = auth(owner)
    frame = data.telecom_churn(150)
    preview = _preview(client, headers, frame, name="internet_service_churn.csv")
    assert preview["analysis_type"] == "churn"

    response = _commit(client, headers, frame, preview, name="internet_service_churn.csv")
    assert response.status_code == 200, response.text

    status = client.get("/api/upload/status", headers=auth(owner)).json()
    assert status["schema"] == "churn"
    assert status["modules"]["dashboard"] is True

    dashboard = client.get("/api/dashboard", headers=auth(owner)).json()
    assert dashboard["mode"] == "adaptive"
    assert dashboard["status"] == "ready"
    assert any(card["label"].lower().startswith("churn") for card in dashboard["summary"])
    assert "sales transaction history" not in json.dumps(dashboard)

    behavior = client.get("/api/behavior", headers=auth(owner)).json()
    assert behavior["mode"] == "adaptive"
    assert behavior["has_data"] is True

    segments = client.get("/api/segments", headers=auth(owner)).json()
    assert segments["mode"] == "adaptive"
    assert segments["sections"]

    report = client.get("/api/analysis/report", headers=auth(owner)).json()
    assert report["mode"] == "adaptive"
    assert report["adaptive"]["task"]["type"] == "classification"
    assert report["adaptive"]["task"]["metrics"]["accuracy"] is not None


def test_generic_dataset_gets_profiling_and_eda(client, auth, owner):
    headers = auth(owner)
    frame = data.iris_like(120)
    preview = _preview(client, headers, frame, name="measurements.csv")
    assert preview["analysis_type"] == "generic"

    response = _commit(client, headers, frame, preview, name="measurements.csv")
    assert response.status_code == 200, response.text

    report = client.get("/api/analysis/report", headers=auth(owner)).json()
    assert report["mode"] == "adaptive"
    assert report["dataset_type"] == "generic"
    assert report["adaptive"]["eda"]["numeric"]
    assert report["adaptive"]["clusters"] is not None
    assert report["profile"]["rows"] == 120


def test_server_rejects_commit_when_required_field_is_missing(client, auth, owner):
    headers = auth(owner)
    frame = data.sales_missing_required()
    preview = _preview(client, headers, frame)
    assert preview["validation"]["ready"] is False

    mapping = {
        key: decision["value"]
        for key, decision in preview["mapping"].items()
        if decision["value"]
    }
    response = client.post(
        "/api/upload/commit",
        files={"file": ("broken.csv", csv_bytes(frame), "text/csv")},
        data={"schema": "sales", "mapping": json.dumps(mapping), "task": "forecast", "target": "sales"},
        headers=auth(owner),
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["message"]
    assert detail["validation"]["errors"] >= 1

    status = client.get("/api/upload/status", headers=auth(owner)).json()
    assert status["has_data"] is False


def test_churn_commit_without_label_is_rejected(client, auth, owner):
    headers = auth(owner)
    frame = data.telecom_churn(80)
    preview = _preview(client, headers, frame)
    mapping = {
        key: decision["value"]
        for key, decision in preview["mapping"].items()
        if decision["value"]
    }
    mapping["churn_status"] = ""  # try to clear the required label
    response = client.post(
        "/api/upload/commit",
        files={"file": ("churn.csv", csv_bytes(frame), "text/csv")},
        data={"schema": "churn", "mapping": json.dumps(mapping), "task": "classification", "target": "churn_status"},
        headers=auth(owner),
    )
    assert response.status_code == 422


def test_workspaces_cannot_see_each_others_datasets(client, auth, owner):
    other = f"other-{owner}"
    frame = data.sales_standard(60)
    preview = _preview(client, auth(owner), frame)
    response = _commit(client, auth(owner), frame, preview)
    assert response.status_code == 200
    dataset_id = response.json()["dataset"]["id"]

    stranger_status = client.get("/api/upload/status", headers=auth(other)).json()
    assert stranger_status["has_data"] is False
    assert stranger_status["dataset"] is None

    stranger_report = client.get("/api/analysis/report", headers=auth(other))
    assert stranger_report.status_code == 404

    stranger_datasets = client.get("/api/datasets", headers=auth(other)).json()
    assert stranger_datasets["datasets"] == []

    activate = client.post(f"/api/datasets/{dataset_id}/activate", headers=auth(other))
    assert activate.status_code == 404

    delete = client.delete(f"/api/datasets/{dataset_id}", headers=auth(other))
    assert delete.status_code == 404


def test_switching_between_stored_datasets_restores_its_analytics(client, auth, owner):
    headers = auth(owner)
    sales = data.sales_standard(60)
    churn = data.telecom_churn(80)

    sales_preview = _preview(client, headers, sales, name="sales.csv")
    assert _commit(client, headers, sales, sales_preview, name="sales.csv").status_code == 200

    churn_preview = _preview(client, headers, churn, name="churn.csv")
    assert _commit(client, headers, churn, churn_preview, name="churn.csv").status_code == 200

    listing = client.get("/api/datasets", headers=auth(owner)).json()
    assert len(listing["datasets"]) == 2
    sales_id = next(item["id"] for item in listing["datasets"] if item["schema"] == "sales")

    activate = client.post(f"/api/datasets/{sales_id}/activate", headers=auth(owner))
    assert activate.status_code == 200

    status = client.get("/api/upload/status", headers=auth(owner)).json()
    assert status["schema"] == "sales"
    assert status["row_count"] == 60

    behavior = client.get("/api/behavior", headers=auth(owner)).json()
    assert behavior["has_data"] is True
    assert behavior.get("dataset_type") != "churn"


def test_upload_rejects_unsupported_files_and_empty_payloads(client, auth, owner):
    response = client.post(
        "/api/upload/preview",
        files={"file": ("notes.json", b'{"a": 1}', "application/json")},
        headers=auth(owner),
    )
    assert response.status_code == 400

    response = client.post(
        "/api/upload/preview",
        files={"file": ("empty.csv", b"", "text/csv")},
        headers=auth(owner),
    )
    assert response.status_code == 400
