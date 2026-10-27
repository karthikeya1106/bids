from services.profiling import infer_column_type, profile_dataframe

from tests import data


def test_infers_semantic_types():
    frame = data.sales_standard(40)
    dtype, _ = infer_column_type(frame["Order Date"], "Order Date")
    assert dtype == "datetime"
    dtype, _ = infer_column_type(frame["Sales"], "Sales")
    assert dtype == "numeric"
    dtype, _ = infer_column_type(frame["Order ID"], "Order ID")
    assert dtype == "identifier"
    dtype, _ = infer_column_type(frame["Category"], "Category")
    assert dtype == "categorical"


def test_profile_reports_structure_and_quality():
    frame = data.sales_with_duplicates_and_gaps()
    profile = profile_dataframe(frame)

    assert profile["rows"] == len(frame)
    assert profile["columns"] == len(frame.columns)
    assert profile["duplicate_rows"] == 10
    ids = {column["name"]: column for column in profile["column_profiles"]}
    # The ten duplicated rows also carry the cleared customer id.
    assert ids["Customer ID"]["missing"] == 20
    findings = {finding["id"] for finding in profile["quality"]}
    assert "duplicate_rows" in findings


def test_time_coverage_is_detected():
    frame = data.sales_standard(120)
    profile = profile_dataframe(frame)
    coverage = profile["time_coverage"]
    assert coverage is not None
    assert coverage["column"] == "Order Date"
    assert coverage["periods"] > 3
    assert coverage["frequency"] in {"daily", "2-3 days", "weekly", "fortnightly", "monthly"}


def test_numeric_summary_and_correlations():
    frame = data.sales_standard(120)
    profile = profile_dataframe(frame)
    sales = next(column for column in profile["column_profiles"] if column["name"] == "Sales")
    assert sales["mean"] is not None
    assert sales["max"] >= sales["min"]
    pairs = {(pair["a"], pair["b"]) for pair in profile["correlations"]}
    assert ("Sales", "Profit") in pairs or ("Profit", "Sales") in pairs


def test_categorical_only_dataset_has_no_time_or_numeric():
    profile = profile_dataframe(data.categorical_only(60))
    assert profile["time_coverage"] is None
    assert profile["type_counts"]["numeric"] == 0
    assert profile["type_counts"]["categorical"] >= 2
