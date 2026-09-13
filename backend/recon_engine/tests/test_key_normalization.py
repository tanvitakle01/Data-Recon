"""Coverage for engine.key_normalization.canonicalize_key_column — the
per-column, value-based reshaping that lets a business-key join succeed even
when the source and target sides serialize the same date or numeric
identifier differently."""

from __future__ import annotations

import pandas as pd

from backend.recon_engine.engine.key_normalization import canonicalize_key_column


def test_iso_dates_pass_through_unchanged():
    series = pd.Series(["2026-09-04", "2026-09-14"])
    out = canonicalize_key_column(series)
    assert out.tolist() == ["2026-09-04", "2026-09-14"]


def test_slash_dates_canonicalize_to_iso():
    series = pd.Series(["9/4/2026", "9/14/2026"])
    out = canonicalize_key_column(series)
    assert out.tolist() == ["2026-09-04", "2026-09-14"]


def test_dotted_short_year_dates_canonicalize_to_iso():
    series = pd.Series(["04.09.26", "14.09.26"])
    out = canonicalize_key_column(series)
    # day=04, month=09 (04 <= 12 for month position, but 14 > 12 forces
    # position 0 as the day) -> year-last, day-first order.
    assert out.tolist() == ["2026-09-04", "2026-09-14"]


def test_two_different_date_formats_converge_on_the_same_key():
    """The actual bug this fixes: a source column already in ISO and a
    target column in un-padded M/D/YYYY must produce IDENTICAL canonical
    values for the same calendar day, even though _build_key never compares
    the two columns against each other to decide how to parse either one."""
    source = canonicalize_key_column(pd.Series(["2026-09-04"]))
    target = canonicalize_key_column(pd.Series(["9/4/2026"]))
    assert source.tolist() == target.tolist() == ["2026-09-04"]


def test_float_artifact_id_canonicalizes_to_bare_integer_string():
    series = pd.Series([786293.0, 20041855.0])
    out = canonicalize_key_column(series)
    assert out.tolist() == ["786293", "20041855"]


def test_string_and_float_ids_converge_on_the_same_key():
    source = canonicalize_key_column(pd.Series([786293.0]))
    target = canonicalize_key_column(pd.Series(["786293"]))
    assert source.tolist() == target.tolist() == ["786293"]


def test_mostly_numeric_column_with_alpha_suffix_outlier_is_still_canonicalized():
    # A handful of alpha-suffixed material codes shouldn't disqualify the
    # whole column from numeric canonicalization (real ECC/IBP product
    # master data is overwhelmingly numeric with the occasional lettered
    # suffix); the outlier itself is left untouched (it never had a
    # float-artifact problem to begin with).
    series = pd.Series([786293.0, 20041855.0, "15017872", "20080370", "15067451R"])
    out = canonicalize_key_column(series)
    assert out.tolist() == ["786293", "20041855", "15017872", "20080370", "15067451R"]


def test_non_numeric_non_date_column_is_left_untouched():
    series = pd.Series(["MAT-A", "MAT-B", "MAT-C"])
    out = canonicalize_key_column(series)
    assert out.tolist() == ["MAT-A", "MAT-B", "MAT-C"]


def test_plain_bare_numeric_ids_are_not_treated_as_dates():
    # No separators -> never date-shaped; still numeric-canonicalized.
    series = pd.Series(["10001", "10002"])
    out = canonicalize_key_column(series)
    assert out.tolist() == ["10001", "10002"]


def test_empty_series_is_returned_unchanged():
    series = pd.Series([], dtype=object)
    out = canonicalize_key_column(series)
    assert out.empty


def test_unparseable_date_values_are_left_as_is():
    # Mostly date-shaped values plus one that fails to actually parse as a
    # calendar date (month 13) -> is_date_like_series still says "date-like"
    # if the rest clear the threshold, but the bad value must not be dropped
    # or corrupted, just passed through.
    series = pd.Series(["2026-01-01", "2026-01-02", "2026-01-03", "2026-13-40"])
    out = canonicalize_key_column(series)
    assert out.tolist()[:3] == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert out.tolist()[3] == "2026-13-40"
