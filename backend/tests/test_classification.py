from services.classifier import classify_dataset, detect_targets
from services.profiling import profile_dataframe

from tests import data


def _classify(frame):
    profile = profile_dataframe(frame)
    return profile, classify_dataset(frame, profile)


def test_standard_sales_file_is_sales():
    frame = data.sales_standard(120)
    _, result = _classify(frame)
    assert result["schema"] == "sales"
    assert result["confidence"] >= 60
    assert any("required fields present" in reason for reason in result["reasons"])


def test_telecom_churn_file_is_not_sales_and_maps_usage_fields():
    frame = data.telecom_churn(120)
    _, result = _classify(frame)

    assert result["schema"] == "churn"
    mapping = result["mapping"]
    assert mapping["tenure"]["column"] == "Account length"
    assert mapping["voicemail_msgs"]["column"] == "Number vmail messages"
    assert mapping["day_mins"]["column"] == "Total day minutes"
    assert mapping["churn_status"]["column"] == "Churn"

    # None of the telecom measures may leak into sales/order fields.
    for field in ("order_id", "order_date", "sales", "profit"):
        assert field not in mapping or mapping[field]["column"] is None


def test_unfamiliar_numeric_file_falls_back_to_generic():
    _, result = _classify(data.iris_like(90))
    assert result["schema"] == "generic"
    assert result["ambiguous"] is True
    assert result["confidence"] == 0
    assert all(reason for reason in result["reasons"])


def test_churn_target_and_tasks_are_detected():
    frame = data.telecom_churn(120)
    profile = profile_dataframe(frame)
    targets = detect_targets(profile)
    assert any(target["column"] == "Churn" and target["task"] == "classification" for target in targets)

    result = classify_dataset(frame, profile)
    supported = result["supported_tasks"]
    assert supported["classification"]["available"] is True
    assert supported["clustering"]["available"] is True
    assert supported["forecast"]["available"] is False


def test_marketing_file_is_classified_as_marketing():
    import pandas as pd

    frame = pd.DataFrame({
        "campaign_id": [f"CMP{i}" for i in range(80)],
        "date": pd.date_range("2024-01-01", periods=80, freq="D").strftime("%Y-%m-%d"),
        "channel": [["search", "social", "email"][i % 3] for i in range(80)],
        "spend": [100 + i for i in range(80)],
        "impressions": [1000 + i * 10 for i in range(80)],
        "clicks": [50 + i for i in range(80)],
        "conversions": [5 + (i % 7) for i in range(80)],
    })
    _, result = _classify(frame)
    assert result["schema"] == "marketing"
