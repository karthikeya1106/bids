from services.classifier import resolve_task
from services.mapping import suggest_mapping
from services.profiling import profile_dataframe
from services.schemas import CHURN, GENERIC, SALES
from services.validation import modules_supported, validate_dataset

from tests import data


def _validate(frame, schema=SALES, task="forecast", target="sales", overrides=None):
    profile = profile_dataframe(frame)
    decisions = suggest_mapping(frame, profile, schema)
    mapping = {key: decision["value"] for key, decision in decisions.items() if decision["value"]}
    mapping.update(overrides or {})
    return profile, validate_dataset(frame, profile, schema, mapping, task, target)


def test_valid_sales_file_passes():
    profile, validation = _validate(data.sales_standard(80))
    assert validation["ready"] is True
    assert validation["errors"] == 0
    assert validation["forecast"]["available"] is True
    assert validation["capabilities"]["has_customer"] is True


def test_forecast_availability_matches_validation():
    # A gappy timeline must not be offered as a forecast task and then rejected
    # by validation of the same file.
    frame = data.sales_sparse_timeline(60)
    profile = profile_dataframe(frame)
    resolved = resolve_task(SALES, profile, "", None)
    assert resolved["supported_tasks"]["forecast"]["available"] is False
    assert resolved["task"] == "eda"
    assert "large gaps" in resolved["supported_tasks"]["forecast"]["reason"]

    decisions = suggest_mapping(frame, profile, SALES)
    mapping = {key: decision["value"] for key, decision in decisions.items() if decision["value"]}
    assert validate_dataset(frame, profile, SALES, mapping, "eda", None)["ready"] is True
    strict = validate_dataset(frame, profile, SALES, mapping, "forecast", "sales")
    assert strict["ready"] is False
    assert any(check["id"] == "task:forecast" and check["status"] == "fail" for check in strict["checks"])


def test_missing_required_field_blocks_ingestion():
    profile, validation = _validate(data.sales_missing_required())
    assert validation["ready"] is False
    assert validation["errors"] >= 1
    assert "order_date" in validation["required_missing"]


def test_wrong_type_in_required_measure_blocks_ingestion():
    frame = data.sales_standard(40)
    profile = profile_dataframe(frame)
    decisions = suggest_mapping(frame, profile, SALES)
    mapping = {key: decision["value"] for key, decision in decisions.items() if decision["value"]}
    mapping["sales"] = "Profit"  # valid numeric, to prove the file still passes
    assert validate_dataset(frame, profile, SALES, mapping, "forecast", "sales")["ready"] is True

    mapping["sales"] = "Product Name"
    validation = validate_dataset(frame, profile, SALES, mapping, "forecast", "sales")
    assert validation["ready"] is False
    assert any(check["id"] == "type:sales" and check["status"] == "fail" for check in validation["checks"])


def test_missing_optional_fields_are_allowed_and_reported():
    frame = data.sales_standard(60).drop(columns=["Profit", "Discount"])
    _, validation = _validate(frame)
    assert validation["ready"] is True
    assert validation["capabilities"]["has_profit"] is False
    assert validation["capabilities"]["has_discount"] is False


def test_duplicate_rows_and_missing_values_warn_without_blocking():
    _, validation = _validate(data.sales_with_duplicates_and_gaps())
    assert validation["ready"] is True
    assert validation["warnings"] >= 1
    statuses = {check["id"]: check["status"] for check in validation["checks"]}
    assert statuses.get("duplicate_rows") in {"warn", "info"}


def test_forecast_is_refused_without_a_timeline():
    frame = data.categorical_only(80)
    profile = profile_dataframe(frame)
    validation = validate_dataset(frame, profile, GENERIC, {}, "forecast", None)
    assert validation["forecast"] is None or validation["forecast"]["available"] is False
    assert validation["ready"] is False


def test_classification_readiness_for_churn():
    frame = data.telecom_churn(120)
    profile, validation = _validate(
        frame, CHURN, task="classification", target="churn_status"
    )
    assert validation["ready"] is True
    check = next(item for item in validation["checks"] if item["id"] == "task:classification")
    assert check["status"] == "pass"
    assert "classes" in check["detail"]


def test_classification_fails_without_a_label():
    frame = data.sales_standard(80)
    profile = profile_dataframe(frame)
    decisions = suggest_mapping(frame, profile, SALES)
    mapping = {key: decision["value"] for key, decision in decisions.items() if decision["value"]}
    validation = validate_dataset(frame, profile, SALES, mapping, "classification", None)
    assert validation["ready"] is False


def test_module_support_matches_the_schema():
    sales_modules = modules_supported("sales", {"has_customer": True, "has_time": True}, {"available": True})
    assert sales_modules["dashboard"] is True
    assert sales_modules["adaptive_report"] is False

    churn_modules = modules_supported("churn", {"has_customer": True}, None)
    assert churn_modules["dashboard"] is False
    assert churn_modules["analysis"] is True
