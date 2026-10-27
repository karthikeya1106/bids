import pandas as pd

from routers.upload import _canonical_mapping, _decorate_decisions
from services.mapping import (
    DERIVED,
    GENERATE,
    apply_derivation,
    suggest_mapping,
)
from services.profiling import profile_dataframe
from services.schemas import CHURN, SALES

from tests import data


def _suggest(frame, schema=SALES):
    profile = profile_dataframe(frame)
    decisions = suggest_mapping(frame, profile, schema)
    return profile, decisions


def test_alternative_sales_names_are_mapped():
    frame = data.sales_alt_names(80)
    _, decisions = _suggest(frame)

    assert decisions["sales"]["column"] == "Sales_Amount"
    assert decisions["order_date"]["column"] == "purchase_date"
    assert decisions["customer_id"]["column"] == "client_id"
    assert decisions["order_id"]["column"] == "txn_id"
    assert decisions["quantity"]["column"] == "Units"
    assert decisions["category"]["column"] == "Product_Category"
    assert decisions["sales"]["confidence"] == "high"


def test_each_source_column_is_used_at_most_once():
    frame = data.telecom_churn(80)
    _, decisions = _suggest(frame, CHURN)
    columns = [decision["column"] for decision in decisions.values() if decision["column"]]
    assert len(columns) == len(set(columns))


def test_generated_identifier_is_labelled_not_invented():
    frame = data.sales_alt_names(60).drop(columns=["txn_id"])
    _, decisions = _suggest(frame)
    order_id = decisions["order_id"]
    assert order_id["value"] == GENERATE
    assert order_id["status"] == "generated"
    assert any("technical row index" in reason for reason in order_id["reasons"])


def test_unrelated_text_is_not_forced_into_a_field():
    frame = data.iris_like(60)
    _, decisions = _suggest(frame)
    mapped = {key: value["column"] for key, value in decisions.items() if value["column"]}
    assert mapped == {}


def test_manual_override_and_clear_are_reflected():
    frame = data.sales_standard(60)
    profile = profile_dataframe(frame)
    decisions = suggest_mapping(frame, profile, SALES)

    updated = _decorate_decisions(
        decisions,
        {"sales": "Profit", "profit": ""},
        frame,
        profile,
    )
    assert updated["sales"]["status"] == "manual"
    assert updated["sales"]["column"] == "Profit"
    assert updated["profit"]["status"] == "unmapped"
    assert updated["profit"]["value"] == ""

    canonical = _canonical_mapping(updated, {"sales": "Profit", "profit": ""})
    assert canonical["sales"] == "Profit"
    assert canonical["profit"] == ""


def test_derived_total_charge_requires_real_inputs():
    frame = data.telecom_churn(60)
    _, decisions = _suggest(frame, CHURN)
    derived = decisions["total_charge_derived"]
    assert derived["status"] == "derived"
    assert set(derived["derived_from"]) == {"day_charge", "eve_charge", "night_charge", "intl_charge"}

    assert apply_derivation(
        "sum_charges",
        {"day_charge": 10.0, "eve_charge": 5.5, "night_charge": 4.5, "intl_charge": 2.0},
    ) == 22.0
    assert apply_derivation("sum_charges", {"day_charge": 10.0}) is None
    assert apply_derivation("profit_margin", {"profit": 50.0, "sales": 0.0}) is None


def test_derivation_is_unavailable_when_source_fields_missing():
    frame = data.telecom_churn(60).drop(columns=["Total intl charge"])
    _, decisions = _suggest(frame, CHURN)
    assert decisions["total_charge_derived"]["status"] in {"unavailable", "unmapped"}
    assert sum(1 for decision in decisions.values() if decision["status"] == "derived") == 0


def test_repeated_customer_key_maps_to_the_id_not_the_name():
    # A customer id repeats once per order; that must not disqualify it, and it
    # must not be consumed by the free-text customer name field instead.
    frame = data.sales_standard(90)
    frame = frame.drop(columns=["Customer Name"])
    _, decisions = _suggest(frame)

    assert decisions["customer_id"]["column"] == "Customer ID"
    assert decisions["customer_id"]["status"] == "auto"
    assert decisions["customer_name"]["column"] in (None, "")


def test_name_field_is_never_filled_with_identifier_values():
    frame = data.sales_standard(60)
    _, decisions = _suggest(frame)
    assert decisions["customer_id"]["column"] == "Customer ID"
    assert decisions["customer_name"]["column"] == "Customer Name"


def test_incompatible_type_is_not_auto_mapped():
    frame = data.sales_standard(40)
    frame["Profit"] = "n/a"
    profile = profile_dataframe(frame)
    decisions = suggest_mapping(frame, profile, SALES)
    assert decisions["profit"]["column"] in (None, "") or decisions["profit"]["status"] != "auto"
