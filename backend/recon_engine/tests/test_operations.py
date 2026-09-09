from __future__ import annotations

import math

import pandas as pd
import pytest

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


def test_aggregate_group_matches_group_by_and_aggregate_example():
    # PRD example: group by Material/Plant/Date, sum Quantity.
    df = pd.DataFrame({
        "Material": ["A", "A", "A"],
        "Plant": ["P1", "P1", "P2"],
        "Date": ["2024-01-01", "2024-01-01", "2024-01-01"],
        "Quantity": [10, 15, 5],
    })
    out = ops.aggregate_group(
        df, None,
        {"by": ["Material", "Plant", "Date"], "aggregations": [{"field": "Quantity", "func": "sum"}]},
    )
    result = {(r.Material, r.Plant, r.Date): r.Quantity for r in out.itertuples()}
    assert result == {("A", "P1", "2024-01-01"): 25, ("A", "P2", "2024-01-01"): 5}


def test_aggregate_group_multiple_aggregations_multiple_fields():
    df = pd.DataFrame({"k": ["x", "x", "y"], "v": [1, 2, 3], "w": [10, 20, 30]})
    out = ops.aggregate_group(
        df, None,
        {
            "by": ["k"],
            "aggregations": [
                {"field": "v", "func": "sum"},
                {"field": "w", "func": "average"},
            ],
        },
    )
    by_k = {r.k: (r.v, r.w) for r in out.itertuples()}
    assert by_k == {"x": (3, 15.0), "y": (3, 30.0)}


def test_aggregate_group_count_and_min_max():
    df = pd.DataFrame({"k": ["x", "x", "x"], "v": [5, 1, 9]})
    out = ops.aggregate_group(
        df, None,
        {
            "by": ["k"],
            "aggregations": [
                {"field": "v", "func": "count"},
            ],
        },
    )
    assert out["v"].iloc[0] == 3

    out_min = ops.aggregate_group(df, None, {"by": ["k"], "aggregations": [{"field": "v", "func": "min"}]})
    assert out_min["v"].iloc[0] == 1
    out_max = ops.aggregate_group(df, None, {"by": ["k"], "aggregations": [{"field": "v", "func": "max"}]})
    assert out_max["v"].iloc[0] == 9


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


def test_remove_leading_zeros_strips_the_embedded_numeric_run_not_the_whole_string():
    # A naive str.lstrip("0") never fires here because the string doesn't
    # START with a digit — the numeric run is embedded after an alpha prefix.
    df = pd.DataFrame({"a": ["FG0006", "FG800"]})
    out = ops.remove_leading_zeros(df, "a", {})
    assert out["a"].tolist() == ["FG6", "FG800"]


def test_remove_leading_zeros_min_width_stops_short_of_bare_digits():
    df = pd.DataFrame({"a": ["FG0006", "FG0007", "0006"]})
    out = ops.remove_leading_zeros(df, "a", {"min_width": 2})
    assert out["a"].tolist() == ["FG06", "FG07", "06"]


def test_remove_leading_zeros_min_width_all_zero_run():
    df = pd.DataFrame({"a": ["FG000"]})
    out = ops.remove_leading_zeros(df, "a", {"min_width": 2})
    assert out["a"].tolist() == ["FG00"]


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


# ── new primitives ────────────────────────────────────────────────────────────

def test_pad_leading_zeros_is_inverse_of_remove_leading_zeros():
    df = pd.DataFrame({"a": ["5006", "FG6", None]}, dtype=object)
    out = ops.pad_leading_zeros(df, "a", {"width": 6})
    assert out["a"].tolist()[:2] == ["005006", "FG000006"]
    assert pd.isna(out["a"].iloc[2])


def test_pad_leading_zeros_round_trips_with_remove_leading_zeros():
    df = pd.DataFrame({"a": ["FG0006"]})
    stripped = ops.remove_leading_zeros(df, "a", {"min_width": 2})
    assert stripped["a"].iloc[0] == "FG06"
    padded_back = ops.pad_leading_zeros(stripped, "a", {"width": 4})
    assert padded_back["a"].iloc[0] == "FG0006"


def test_pad_leading_zeros_leaves_already_wide_values_unchanged():
    df = pd.DataFrame({"a": ["123456"]})
    out = ops.pad_leading_zeros(df, "a", {"width": 4})
    assert out["a"].iloc[0] == "123456"


def test_date_bucket_month_start_and_end():
    df = pd.DataFrame({"d": ["2025-08-19", "bad"]})
    start = ops.date_bucket(df, "d", {"granularity": "month", "anchor": "start"})
    assert start["d"].iloc[0] == "2025-08-01"
    bad = start["d"].iloc[1]
    assert bad is None or (isinstance(bad, float) and math.isnan(bad))
    end = ops.date_bucket(df, "d", {"granularity": "month", "anchor": "end"})
    assert end["d"].iloc[0] == "2025-08-31"


def test_date_bucket_week_and_quarter_and_year():
    df = pd.DataFrame({"d": ["2025-08-19"]})
    assert ops.date_bucket(df, "d", {"granularity": "quarter"})["d"].iloc[0] == "2025-07-01"
    assert ops.date_bucket(df, "d", {"granularity": "year"})["d"].iloc[0] == "2025-01-01"
    # ISO week starting Monday: 2025-08-19 is a Tuesday -> Monday 2025-08-18.
    assert ops.date_bucket(df, "d", {"granularity": "week"})["d"].iloc[0] == "2025-08-18"


def test_date_window_filter_open_and_closed_bounds():
    df = pd.DataFrame({"d": ["2025-08-01", "2025-08-15", "2025-09-01", "bad"]})
    run_date = pd.Timestamp("2025-08-15")

    closed = ops.date_window_filter(
        df, "d", {"_run_date": run_date, "lower_offset_days": -14, "upper_offset_days": 0}
    )
    assert closed["d"].tolist() == ["2025-08-01", "2025-08-15"]

    open_lower = ops.date_window_filter(df, "d", {"_run_date": run_date, "upper_offset_days": 0})
    assert open_lower["d"].tolist() == ["2025-08-01", "2025-08-15"]

    open_upper = ops.date_window_filter(df, "d", {"_run_date": run_date, "lower_offset_days": 0})
    assert open_upper["d"].tolist() == ["2025-08-15", "2025-09-01"]


def test_relative_date_reassign_rolls_past_due_forward():
    df = pd.DataFrame({"d": ["2025-08-10", "2025-08-20"]})  # run_date = 2025-08-15 (Friday)
    run_date = pd.Timestamp("2025-08-15")
    out = ops.relative_date_reassign(
        df, "d", {"_run_date": run_date, "date_condition": "lt", "offset_days": 1}
    )
    assert out["d"].tolist() == ["2025-08-16", "2025-08-20"]  # only the past-due row rolls


def test_relative_date_reassign_weekday_exception():
    df = pd.DataFrame({"d": ["2025-08-10"]})
    saturday_run_date = pd.Timestamp("2025-08-16")  # a Saturday
    out = ops.relative_date_reassign(
        df, "d",
        {
            "_run_date": saturday_run_date,
            "date_condition": "lt",
            "offset_days": 1,
            "weekday_exception": {"on_weekday": "saturday", "offset_days": 2},
        },
    )
    assert out["d"].iloc[0] == "2025-08-18"  # +2, not +1, because run_date is Saturday


def test_relative_date_reassign_rejects_malformed_weekday_exception():
    df = pd.DataFrame({"d": ["2025-08-10"]})
    run_date = pd.Timestamp("2025-08-16")
    with pytest.raises(ValueError, match="weekday_exception"):
        ops.relative_date_reassign(
            df, "d",
            {
                "_run_date": run_date,
                "date_condition": "lt",
                "offset_days": 1,
                "weekday_exception": "saturday",  # not a dict — mid-edit JSON, or a bad LLM output
            },
        )


def test_relative_date_reassign_passes_through_when_condition_false():
    df = pd.DataFrame({"d": ["2025-08-20", None]}, dtype=object)
    run_date = pd.Timestamp("2025-08-15")
    out = ops.relative_date_reassign(
        df, "d", {"_run_date": run_date, "date_condition": "lt", "offset_days": 1}
    )
    assert out["d"].iloc[0] == "2025-08-20"
    assert pd.isna(out["d"].iloc[1])


def test_aggregate_group_first_reducer_passes_through_a_representative_value():
    df = pd.DataFrame({"k": ["x", "x", "y"], "note": ["first-note", "second-note", "only-note"]})
    out = ops.aggregate_group(df, None, {"by": ["k"], "aggregations": [{"field": "note", "func": "first"}]})
    by_k = dict(zip(out["k"], out["note"]))
    assert by_k == {"x": "first-note", "y": "only-note"}


def test_aggregate_group_multi_field_group_by_multi_measure():
    # The monthly-bucket-by-product-plant-customer case: multiple `by`
    # columns AND multiple measures (sum + average) in one call.
    df = pd.DataFrame({
        "product": ["A", "A", "A", "B"],
        "plant": ["P1", "P1", "P2", "P1"],
        "customer": ["C1", "C1", "C1", "C1"],
        "qty": [10, 15, 5, 7],
        "price": [2.0, 3.0, 4.0, 1.0],
    })
    out = ops.aggregate_group(
        df, None,
        {
            "by": ["product", "plant", "customer"],
            "aggregations": [
                {"field": "qty", "func": "sum"},
                {"field": "price", "func": "average"},
            ],
        },
    )
    result = {
        (r.product, r.plant, r.customer): (r.qty, r.price) for r in out.itertuples()
    }
    assert result == {
        ("A", "P1", "C1"): (25, 2.5),
        ("A", "P2", "C1"): (5, 4.0),
        ("B", "P1", "C1"): (7, 1.0),
    }
