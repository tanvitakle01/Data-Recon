from __future__ import annotations

import math

import pandas as pd

from backend.recon_engine.operations import ops


def test_identity_cast_string_preserves_nulls():
    # Excel/SAP frames load as dtype=object; mirror that here.
    df = pd.DataFrame({"a": [1, 2, None]}, dtype=object)
    out = ops.identity_cast_string(df, "a", {})
    assert out["a"].tolist()[:2] == ["1", "2"]
    assert pd.isna(out["a"].iloc[2])


def test_trim_string():
    df = pd.DataFrame({"a": ["  x ", "y"]})
    out = ops.trim_string(df, "a", {})
    assert out["a"].tolist() == ["x", "y"]


def test_numeric_cast_coerces():
    df = pd.DataFrame({"a": ["1", "2.5", "nope"]})
    out = ops.numeric_cast(df, "a", {})
    assert out["a"].iloc[0] == 1.0
    assert out["a"].iloc[1] == 2.5
    assert math.isnan(out["a"].iloc[2])


def test_date_parse_reformats():
    df = pd.DataFrame({"d": ["31.12.2023", "01.01.2024", "bad"]})
    out = ops.date_parse(df, "d", {"source_format": "DD.MM.YYYY", "canonical_format": "YYYY-MM-DD"})
    assert out["d"].iloc[0] == "2023-12-31"
    assert out["d"].iloc[1] == "2024-01-01"
    assert out["d"].iloc[2] is None or (isinstance(out["d"].iloc[2], float) and math.isnan(out["d"].iloc[2]))


def test_rename_field():
    df = pd.DataFrame({"a": [1]})
    out = ops.rename_field(df, "a", {"to": "b"})
    assert list(out.columns) == ["b"]


def test_reject_null_drops_blank_and_null():
    df = pd.DataFrame({"a": ["x", "", None, "  ", "y"]})
    out = ops.reject_null(df, "a", {})
    assert out["a"].tolist() == ["x", "y"]


def test_exclude_value():
    df = pd.DataFrame({"a": ["keep", "drop", "keep2"]})
    out = ops.exclude_value(df, "a", {"values": ["drop"]})
    assert out["a"].tolist() == ["keep", "keep2"]


def test_include_value():
    df = pd.DataFrame({"a": ["5875", "1000", "5875"]})
    out = ops.include_value(df, "a", {"values": ["5875"]})
    assert out["a"].tolist() == ["5875", "5875"]


def test_group_by_dedups():
    df = pd.DataFrame({"k": ["x", "x", "y"], "v": [1, 2, 3]})
    out = ops.group_by(df, None, {"by": ["k"]})
    assert out["k"].tolist() == ["x", "y"]


def test_sum_aggregate():
    df = pd.DataFrame({"k": ["x", "x", "y"], "v": [1, 2, 3]})
    out = ops.sum_aggregate(df, "v", {"by": ["k"]})
    result = dict(zip(out["k"], out["v"]))
    assert result == {"x": 3, "y": 3}


def test_exact_match_numeric_and_string():
    src = pd.Series(["10", "abc", "5"])
    tgt = pd.Series(["10.0", "ABC", "6"])
    out = ops.exact_match(src, tgt, {"options": {"case_insensitive": True}})
    assert out.tolist() == [True, True, False]


def test_tolerance_match():
    src = pd.Series([100.0, 100.0])
    tgt = pd.Series([101.0, 110.0])
    out = ops.tolerance_match(src, tgt, {"tolerance": 5})
    assert out.tolist() == [True, False]


# ── value-transform ops ──────────────────────────────────────────────────────

def test_prepend_prefix_preserves_nulls():
    df = pd.DataFrame({"a": ["5006", "1000", None]}, dtype=object)
    out = ops.prepend_prefix(df, "a", {"value": "PL"})
    assert out["a"].tolist()[:2] == ["PL5006", "PL1000"]
    assert pd.isna(out["a"].iloc[2])


def test_append_suffix():
    df = pd.DataFrame({"a": ["5006", "1000"]})
    out = ops.append_suffix(df, "a", {"value": "@S21400"})
    assert out["a"].tolist() == ["5006@S21400", "1000@S21400"]


def test_prefix_then_suffix_matches_objective_example():
    """Plant '5006' --prepend PL--> --append @S21400--> 'PL5006@S21400'."""
    df = pd.DataFrame({"Plant": ["5006"]})
    df = ops.prepend_prefix(df, "Plant", {"value": "PL"})
    df = ops.append_suffix(df, "Plant", {"value": "@S21400"})
    assert df["Plant"].iloc[0] == "PL5006@S21400"


def test_remove_leading_zeros():
    df = pd.DataFrame({"a": ["005006", "0", "000", "12"]})
    out = ops.remove_leading_zeros(df, "a", {})
    assert out["a"].tolist() == ["5006", "0", "0", "12"]


def test_replace_value_is_literal_substring():
    df = pd.DataFrame({"m": ["N01-FG01", "N01"]})
    out = ops.replace_value(df, "m", {"from": "N01", "to": "T01"})
    assert out["m"].tolist() == ["T01-FG01", "T01"]


def test_uppercase_lowercase():
    df = pd.DataFrame({"a": ["aB", "Cd"]})
    assert ops.uppercase(df, "a", {})["a"].tolist() == ["AB", "CD"]
    assert ops.lowercase(df, "a", {})["a"].tolist() == ["ab", "cd"]


def test_substring_start_and_length():
    df = pd.DataFrame({"a": ["ABCDEF"]})
    assert ops.substring(df, "a", {"start": 0, "length": 3})["a"].iloc[0] == "ABC"
    assert ops.substring(df, "a", {"start": 2})["a"].iloc[0] == "CDEF"


def test_regex_replace():
    df = pd.DataFrame({"a": ["ab12cd34"]})
    out = ops.regex_replace(df, "a", {"pattern": r"\d+", "replacement": "#"})
    assert out["a"].iloc[0] == "ab#cd#"


def test_concat_fields_into_new_column():
    df = pd.DataFrame({"a": ["x", "y"], "b": ["1", "2"]})
    out = ops.concat_fields(df, None, {"fields": ["a", "b"], "into": "key", "separator": "-"})
    assert out["key"].tolist() == ["x-1", "y-2"]


def test_concat_fields_treats_nulls_as_empty():
    df = pd.DataFrame({"a": ["x", None], "b": ["1", "2"]}, dtype=object)
    out = ops.concat_fields(df, None, {"fields": ["a", "b"], "into": "key", "separator": "|"})
    assert out["key"].tolist() == ["x|1", "|2"]


def test_decimal_round():
    df = pd.DataFrame({"a": ["1.239", "2"]})
    out = ops.decimal_round(df, "a", {"decimals": 2})
    assert out["a"].iloc[0] == 1.24
    assert out["a"].iloc[1] == 2.0


def test_null_to_default_covers_null_and_blank():
    df = pd.DataFrame({"a": ["x", "", None, "  "]}, dtype=object)
    out = ops.null_to_default(df, "a", {"default": "NA"})
    assert out["a"].tolist() == ["x", "NA", "NA", "NA"]


def test_value_mapping_with_and_without_default():
    df = pd.DataFrame({"a": ["1000", "1010", "9999"]})
    mapped = ops.value_mapping(df, "a", {"mapping": {"1000": "A", "1010": "B"}})
    assert mapped["a"].tolist() == ["A", "B", "9999"]  # unmapped unchanged
    with_default = ops.value_mapping(df, "a", {"mapping": {"1000": "A"}, "default": "?"})
    assert with_default["a"].tolist() == ["A", "?", "?"]


def test_conditional_prefix_only_applies_when_numeric():
    df = pd.DataFrame({"a": ["5006", "ABC", "1000"]})
    out = ops.conditional_prefix(df, "a", {"value": "PL", "condition": "numeric"})
    assert out["a"].tolist() == ["PL5006", "ABC", "PL1000"]


def test_conditional_suffix_default_non_empty():
    df = pd.DataFrame({"a": ["x", "", "y"]}, dtype=object)
    out = ops.conditional_suffix(df, "a", {"value": "!"})
    assert out["a"].tolist() == ["x!", "", "y!"]
