"""Coverage for recon_engine.date_detection.is_date_like_series — the cheap,
deterministic (regex-shape + real parse-attempt) check that decides whether
a column's own VALUES look like dates, with no column-name involved at all.
"""

from __future__ import annotations

import pandas as pd

from backend.recon_engine.date_detection import detect_date_format, is_date_like_series


def test_iso_dates_are_date_like():
    assert is_date_like_series(pd.Series(["2024-01-01", "2024-01-02", "2024-01-03"])) is True


def test_dotted_short_year_dates_are_date_like():
    # The exact style from the original design note: "12.04.26".
    assert is_date_like_series(pd.Series(["12.04.26", "01.05.26", "15.06.26"])) is True


def test_slash_dates_are_date_like():
    assert is_date_like_series(pd.Series(["04/12/2026", "05/01/2026"])) is True


def test_plain_numeric_ids_are_not_date_like():
    # No separator -> never matches the date-shaped regex, regardless of how
    # pandas might otherwise be coaxed into parsing a bare number.
    assert is_date_like_series(pd.Series(["10001", "10002", "10003"])) is False


def test_plain_text_codes_are_not_date_like():
    assert is_date_like_series(pd.Series(["MAT-1", "MAT-2", "RAW-1"])) is False


def test_mostly_non_date_values_stay_below_threshold():
    # Only 1 of 5 values is date-shaped -> hit rate 0.2, below the default
    # 0.8 threshold, even though that one value would parse fine on its own.
    series = pd.Series(["MAT-1", "MAT-2", "MAT-3", "MAT-4", "2024-01-01"])
    assert is_date_like_series(series) is False


def test_empty_and_none_series_are_not_date_like():
    assert is_date_like_series(pd.Series([], dtype=object)) is False
    assert is_date_like_series(pd.Series([None, None])) is False
    assert is_date_like_series(None) is False


def test_shaped_but_unparseable_values_are_not_date_like():
    # Matches the digits-with-separators shape but is not a real calendar
    # date (month 13) -> regex hit, parse fails -> not counted as a hit.
    assert is_date_like_series(pd.Series(["13.13.99", "13.13.99", "13.13.99"])) is False


def test_custom_threshold_and_sample_size_are_honored():
    series = pd.Series(["2024-01-01", "MAT-1", "MAT-2", "MAT-3"])
    assert is_date_like_series(series, hit_threshold=0.2) is True
    assert is_date_like_series(series, hit_threshold=0.5) is False


# ── detect_date_format ───────────────────────────────────────────────────────


def test_non_date_column_has_no_detected_format():
    assert detect_date_format(pd.Series(["MAT-1", "MAT-2", "MAT-3"])) is None
    assert detect_date_format(None) is None


def test_iso_format_is_detected_unambiguously():
    spec = detect_date_format(pd.Series(["2026-09-04", "2026-09-14"]))
    assert spec is not None
    assert spec.order == ("Y", "M", "D")
    assert spec.separator == "-"
    assert spec.year_digits == 4
    assert spec.zero_padded is True
    assert spec.ambiguous is False
    assert spec.display() == "YYYY-MM-DD"


def test_unpadded_month_day_first_format_is_detected():
    # "9/4/2026" / "9/14/2026": position 1 (day) exceeds 12 in the second
    # value, unambiguously resolving the order even though every value in
    # isolation could otherwise be read either way.
    spec = detect_date_format(pd.Series(["9/4/2026", "9/14/2026"]))
    assert spec is not None
    assert spec.order == ("M", "D", "Y")
    assert spec.separator == "/"
    assert spec.year_digits == 4
    assert spec.zero_padded is False
    assert spec.ambiguous is False
    assert spec.display() == "M/D/YYYY"


def test_day_first_format_is_detected_when_day_exceeds_12():
    spec = detect_date_format(pd.Series(["14.09.2026", "04.09.2026"]))
    assert spec is not None
    assert spec.order == ("D", "M", "Y")
    assert spec.separator == "."
    assert spec.zero_padded is True
    assert spec.ambiguous is False
    assert spec.display() == "DD.MM.YYYY"


def test_dotted_short_year_format_is_detected():
    spec = detect_date_format(pd.Series(["12.04.26", "15.06.26"]))
    assert spec is not None
    # 15 > 12 unambiguously forces the first position to be the day.
    assert spec.order == ("D", "M", "Y")
    assert spec.year_digits == 2
    assert spec.ambiguous is False


def test_ambiguous_order_defaults_month_first_but_is_flagged():
    # A single repeated date (or a column where every sampled value has both
    # candidate components <= 12) can't be disambiguated from the data alone
    # — this is exactly the real-world case of a static extract whose one
    # KEYFIGUREDATE value is always "9/4/2026".
    spec = detect_date_format(pd.Series(["9/4/2026", "9/4/2026", "9/4/2026"]))
    assert spec is not None
    assert spec.ambiguous is True
    assert spec.order == ("M", "D", "Y")


def test_below_threshold_columns_have_no_detected_format():
    series = pd.Series(["MAT-1", "MAT-2", "MAT-3", "MAT-4", "2024-01-01"])
    assert detect_date_format(series) is None
