from __future__ import annotations

import pytest

from backend.recon_engine.operations import get_operation, is_allowed, list_operations


def test_all_expected_operations_present():
    names = {op["name"] for op in list_operations()}
    expected = {
        "identity_cast_string", "trim_string", "numeric_cast", "date_parse",
        "rename_field", "reject_null", "exclude_value", "group_by",
        "sum_aggregate", "exact_match", "tolerance_match",
    }
    assert expected <= names


def test_unknown_operation_not_allowed():
    assert not is_allowed("os_system")
    with pytest.raises(KeyError):
        get_operation("eval")


def test_validate_reports_unknown_field():
    spec = get_operation("trim_string")
    errors = spec.validate("missing_col", {}, columns=["a", "b"])
    assert any("unknown field" in e for e in errors)


def test_validate_reports_missing_required_param():
    spec = get_operation("date_parse")
    errors = spec.validate("d", {}, columns=["d"])
    assert any("source_format" in e for e in errors)


def test_validate_reports_unexpected_param():
    spec = get_operation("trim_string")
    errors = spec.validate("a", {"bogus": 1}, columns=["a"])
    assert any("unexpected param" in e for e in errors)


def test_validate_field_list_param_checks_membership():
    spec = get_operation("group_by")
    errors = spec.validate(None, {"by": ["a", "ghost"]}, columns=["a", "b"])
    assert any("ghost" in e for e in errors)


def test_validate_sentinel_field_param_allows_sentinel_but_gates_other_values():
    spec = get_operation("relative_date_reassign")
    ok = spec.validate(
        "d", {"date_condition": "lt", "offset_days": 1, "compare_to": "run_date"}, columns=["d"]
    )
    assert ok == []

    real_column = spec.validate(
        "d", {"date_condition": "lt", "offset_days": 1, "compare_to": "other_date"},
        columns=["d", "other_date"],
    )
    assert real_column == []

    hallucinated = spec.validate(
        "d", {"date_condition": "lt", "offset_days": 1, "compare_to": "NotAColumn"}, columns=["d"]
    )
    assert any("NotAColumn" in e for e in hallucinated)


def test_validate_enum_param_rejects_unknown_value():
    spec = get_operation("relative_date_reassign")
    errors = spec.validate("d", {"date_condition": "before", "offset_days": 1}, columns=["d"])
    assert any("date_condition" in e and "before" in e for e in errors)

    bucket = get_operation("date_bucket")
    errors = bucket.validate("d", {"granularity": "annual"}, columns=["d"])
    assert any("granularity" in e and "annual" in e for e in errors)


def test_validate_rejects_measure_field_that_is_also_a_group_by_key():
    spec = get_operation("aggregate_group")
    errors = spec.validate(
        None,
        {"by": ["product", "month"], "aggregations": [{"field": "month", "func": "count"}]},
        columns=["product", "month", "qty"],
    )
    assert any("month" in e and "group-by" in e for e in errors)


def test_validate_allows_disjoint_group_by_and_measures():
    spec = get_operation("aggregate_group")
    errors = spec.validate(
        None,
        {
            "by": ["product", "plant", "month"],
            "aggregations": [{"field": "qty", "func": "sum"}, {"field": "price", "func": "average"}],
        },
        columns=["product", "plant", "month", "qty", "price"],
    )
    assert errors == []
