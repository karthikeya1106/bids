from services.adaptive import (
    build_adaptive_report,
    classify,
    cluster,
    feature_columns,
    forecast,
    prepare_frame,
    regress,
)
from services.profiling import profile_dataframe

from tests import data


def test_classification_reports_holdout_metrics_and_baseline():
    frame = prepare_frame(data.iris_like(150))
    numeric, categorical = feature_columns(frame, "species")
    result = classify(frame, "species", numeric, categorical)

    assert result["available"] is True
    assert result["selected_model"]
    assert 0.0 <= result["metrics"]["accuracy"] <= 1.0
    assert 0.0 <= result["metrics"]["f1_macro"] <= 1.0
    assert result["baseline"]["model"] == "Most-frequent class"
    assert len(result["confusion"]["matrix"]) == len(result["confusion"]["labels"])
    assert result["split"]["test_rows"] > 0
    assert result["notes"]


def test_classification_refuses_a_single_class_target():
    frame = prepare_frame(data.iris_like(40))
    frame["species"] = "setosa"
    numeric, categorical = feature_columns(frame, "species")
    result = classify(frame, "species", numeric, categorical)
    assert result["available"] is False
    assert result["notes"]


def test_regression_reports_real_error_metrics():
    frame = prepare_frame(data.regression_generic(160))
    numeric, categorical = feature_columns(frame, "price")
    result = regress(frame, "price", numeric, categorical)

    assert result["available"] is True
    assert result["metrics"]["mae"] is not None
    assert result["metrics"]["rmse"] is not None
    assert result["metrics"]["r2"] is not None
    assert result["importances"]
    # The generated price is a strong function of size and age.
    assert result["metrics"]["r2"] > 0.5


def test_regression_refuses_a_constant_target():
    frame = prepare_frame(data.regression_generic(60))
    frame["price"] = 100.0
    numeric, categorical = feature_columns(frame, "price")
    result = regress(frame, "price", numeric, categorical)
    assert result["available"] is False


def test_clustering_returns_profiles():
    frame = prepare_frame(data.iris_like(150))
    numeric, _ = feature_columns(frame, None)
    result = cluster(frame, numeric)

    assert result["available"] is True
    assert result["k"] >= 2
    assert result["silhouette"] is not None
    assert len(result["clusters"]) == result["k"]
    assert sum(item["size"] for item in result["clusters"]) == result["rows_used"]


def test_forecast_backtests_and_returns_intervals():
    frame = prepare_frame(data.monthly_timeseries(36))
    result = forecast(frame, "month", "revenue")

    assert result["available"] is True
    assert len(result["forecast"]) == 6
    assert result["metrics"]["mae"] is not None
    assert result["metrics"]["holdout_periods"] >= 3
    for row in result["forecast"]:
        assert row["lower"] <= row["value"] <= row["upper"]


def test_forecast_refuses_data_without_a_timeline():
    frame = prepare_frame(data.categorical_only(60))
    result = forecast(frame, "region", "product")  # no numeric measure, not dates
    assert result["available"] is False
    assert result["notes"]


def test_report_is_adaptive_and_honest_about_unsupported_tasks():
    frame = data.iris_like(120)
    profile = profile_dataframe(frame)

    report = build_adaptive_report(frame, profile, "generic", "eda", None, {})
    assert report["mode"] == "adaptive"
    assert report["eda"]["numeric"]
    assert report["task"] is None
    assert report["clusters"] is not None
    assert report["limitations"]

    requested = build_adaptive_report(frame, profile, "generic", "forecast", None, {"forecast": {"available": False}})
    assert requested["task"] is None
    assert any("could not run" in note for note in requested["limitations"])
