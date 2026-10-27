"""Reclassification of already-stored datasets.

These tests cover the contract the UI depends on: a legacy ``generic`` dataset
is upgraded only when its own columns support a domain template, stored rows are
rebuilt exactly once, manual choices and confirmed targets survive, refusals
leave the dataset untouched, and another workspace can never trigger the
operation.
"""
import json

from db.database import SessionLocal
from db.models import DatasetRow, Order
from tests import data
from tests.conftest import csv_bytes


def _preview(client, headers, frame, schema="auto"):
    response = client.post(
        f"/api/upload/preview?analysis_type={schema}",
        files={"file": ("dataset.csv", csv_bytes(frame), "text/csv")},
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
    response = client.post(
        "/api/upload/commit",
        files={"file": (name, csv_bytes(frame), "text/csv")},
        data={
            "schema": preview["analysis_type"],
            "mapping": json.dumps(mapping),
            "task": preview["task"],
            "target": preview["target"] or "",
            "org_name": "Reclassify Test",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _upload(client, headers, frame, schema="auto", name="dataset.csv"):
    return _commit(client, headers, frame, _preview(client, headers, frame, schema), name)


def _row_count(dataset_id: int) -> int:
    db = SessionLocal()
    try:
        return db.query(DatasetRow).filter(DatasetRow.dataset_id == dataset_id).count()
    finally:
        db.close()


def _reclassify(client, headers, dataset_id, template=None):
    body = {"schema": template} if template else {}
    return client.post(f"/api/datasets/{dataset_id}/reclassify", json=body, headers=headers)


# ─── Legacy generic → churn ──────────────────────────────────────────────────


def test_legacy_generic_telecom_dataset_is_upgraded_to_churn(client, auth, owner):
    headers = auth(owner)
    frame = data.telecom_churn(240)
    uploaded = _upload(client, headers, frame, schema="generic", name="internet_service_churn.csv")
    dataset_id = uploaded["dataset"]["id"]
    assert uploaded["schema"] == "generic"

    response = _reclassify(client, headers, dataset_id)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["changed"] is True
    assert body["status"] == "reclassified"
    assert body["before"]["schema"] == "generic"
    assert body["after"]["schema"] == "churn"
    assert body["after"]["rows"] == 240
    assert body["classification"]["confidence"] >= 55
    assert body["dataset"]["schema"] == "churn"
    # The rows were rebuilt, but not duplicated.
    assert body["rows_rewritten"] == 240
    assert _row_count(dataset_id) == 240

    # The analytics now use the churn template instead of generic EDA.
    report = client.get("/api/analysis/report", headers=headers).json()
    assert report["mode"] == "adaptive"
    assert report["capabilities"]["schema"] == "churn"
    dashboard = client.get("/api/dashboard", headers=headers).json()
    assert dashboard["mode"] == "adaptive"
    assert dashboard["schema_label"] == "Customer Churn Analytics"
    assert "revenue_trend" not in dashboard


def test_repeated_reclassification_is_a_no_op(client, auth, owner):
    headers = auth(owner)
    frame = data.telecom_churn(200)
    dataset_id = _upload(client, headers, frame, schema="generic")["dataset"]["id"]

    first = _reclassify(client, headers, dataset_id)
    assert first.status_code == 200, first.text
    assert first.json()["changed"] is True
    snapshot = client.get(f"/api/datasets/{dataset_id}", headers=headers).json()
    rows_after_first = _row_count(dataset_id)

    second = _reclassify(client, headers, dataset_id)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["changed"] is False
    assert body["status"] == "unchanged"
    assert body["rows_rewritten"] == 0
    assert _row_count(dataset_id) == rows_after_first == snapshot["rows"]

    unchanged = client.get(f"/api/datasets/{dataset_id}", headers=headers).json()
    assert unchanged["row_count" if "row_count" in unchanged else "rows"] == snapshot["rows"]
    assert unchanged["schema"] == "churn"
    assert unchanged["mapping"] == snapshot["mapping"]


# ─── Legacy generic → sales, and repaired mappings ───────────────────────────


def test_legacy_generic_sales_dataset_becomes_sales_with_a_customer_key(client, auth, owner):
    headers = auth(owner)
    frame = data.sales_standard(120)
    dataset_id = _upload(client, headers, frame, schema="generic")["dataset"]["id"]

    response = _reclassify(client, headers, dataset_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["after"]["schema"] == "sales"
    mapping = {entry["field"]: entry for entry in body["mapping"]}
    assert mapping["customer_id"]["column"] == "Customer ID"
    assert mapping["customer_id"]["status"] == "auto"

    db = SessionLocal()
    try:
        orders = db.query(Order).filter(Order.owner_id == owner).all()
        assert len(orders) == 120
        assert sum(1 for order in orders if order.customer_id) == 120
    finally:
        db.close()

    dashboard = client.get("/api/dashboard", headers=headers).json()
    assert dashboard["kpis"], dashboard
    customers = next(kpi for kpi in dashboard["kpis"] if kpi["key"] == "customers")
    assert customers["value"] > 0


def test_manual_mapping_and_confirmed_target_survive(client, auth, owner):
    headers = auth(owner)
    # A legacy generic upload keeps its original column names, so a manual
    # mapping made by the user still refers to a real column.
    frame = data.sales_standard(120)
    dataset_id = _upload(client, headers, frame, schema="generic")["dataset"]["id"]

    db = SessionLocal()
    try:
        from db.models import DatasetMeta

        meta = db.query(DatasetMeta).filter(DatasetMeta.id == dataset_id).first()
        meta.mapping_json = json.dumps({
            "category": {
                "field": "category",
                "label": "Product Category",
                "dtype": "categorical",
                "required": False,
                "value": "Region",
                "column": "Region",
                "status": "manual",
                "confidence": "manual",
                "score": 1.0,
                "reasons": ["selected by the user"],
            }
        })
        meta.target_field = "Sales"
        meta.analysis_task = "regression"
        db.commit()
    finally:
        db.close()

    response = _reclassify(client, headers, dataset_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["after"]["schema"] == "sales"

    mapping = {entry["field"]: entry for entry in body["mapping"]}
    assert mapping["category"]["column"] == "Region"
    assert mapping["category"]["status"] == "manual"
    # A source column still feeds only one field.
    assert mapping["region"]["column"] in (None, "")
    assert body["after"]["target"] == "sales"
    assert body["after"]["task"] == "regression"
    assert not any(item["kind"] == "target_dropped" for item in body["review"])


# ─── Refusals ────────────────────────────────────────────────────────────────


def test_unsupported_template_is_refused_without_touching_the_dataset(client, auth, owner):
    headers = auth(owner)
    frame = data.iris_like(150)
    uploaded = _upload(client, headers, frame, schema="generic")
    dataset_id = uploaded["dataset"]["id"]
    before = client.get(f"/api/datasets/{dataset_id}", headers=headers).json()

    response = _reclassify(client, headers, dataset_id, template="sales")
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert "left unchanged" in detail["message"]
    assert detail["failing"]

    after = client.get(f"/api/datasets/{dataset_id}", headers=headers).json()
    assert after["schema"] == before["schema"] == "generic"
    assert after["rows"] == before["rows"]
    assert _row_count(dataset_id) == before["rows"]


def test_unknown_template_is_a_validation_error(client, auth, owner):
    headers = auth(owner)
    dataset_id = _upload(client, headers, data.sales_standard(60))["dataset"]["id"]
    response = _reclassify(client, headers, dataset_id, template="astrology")
    assert response.status_code == 422


# ─── Authorization ──────────────────────────────────────────────────────────


def test_another_workspace_cannot_reclassify_the_dataset(client, auth, owner):
    headers = auth(owner)
    frame = data.telecom_churn(120)
    dataset_id = _upload(client, headers, frame, schema="generic")["dataset"]["id"]

    intruder = auth(f"intruder-{owner}")
    response = _reclassify(client, intruder, dataset_id)
    assert response.status_code == 404

    # Still generic: the intruder changed nothing.
    detail = client.get(f"/api/datasets/{dataset_id}", headers=headers).json()
    assert detail["schema"] == "generic"


def test_reclassify_requires_a_signed_identity(client, auth, owner):
    dataset_id = _upload(client, auth(owner), data.telecom_churn(120), schema="generic")["dataset"]["id"]
    response = client.post(f"/api/datasets/{dataset_id}/reclassify")
    assert response.status_code == 401


# ─── Capability metadata ─────────────────────────────────────────────────────


def test_reclassification_records_tasks_confidence_and_review_items(client, auth, owner):
    headers = auth(owner)
    dataset_id = _upload(client, headers, data.telecom_churn(200), schema="generic")["dataset"]["id"]

    body = _reclassify(client, headers, dataset_id).json()
    tasks = body["tasks"]
    assert tasks["classification"]["available"] is True
    assert tasks["forecast"]["available"] is False
    assert any(item["kind"] == "target_unset" for item in body["review"])

    listing = client.get("/api/datasets", headers=headers).json()["datasets"]
    stored = next(item for item in listing if item["id"] == dataset_id)
    assert stored["confidence"] is not None
    assert stored["classified_at"]
    assert stored["supported_tasks"]["classification"]["available"] is True
    assert stored["schema"] == "churn"
