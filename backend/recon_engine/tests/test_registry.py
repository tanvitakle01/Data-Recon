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
