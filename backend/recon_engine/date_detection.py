"""Deterministic, value-based date detection.

Whether a key pair is "the date one" — excluded from value-pairing and used
only for corroboration (see ``routes.value_mapping._split_date_pair``) — is
decided by looking at a cheap sample of the column's OWN VALUES: a
date-shaped regex pre-filter, then a real parse attempt via
``pandas.to_datetime``. Never a column-name guess (that's
``recon_engine.field_roles``, still used by Auto mode's column-name-only role
detection) and never an LLM call — this is a fixed-cost check over a small
sample, safe to run on every request.
"""

from __future__ import annotations

import re

import pandas as pd

# Shaped like a date a real-world extract is likely to use: ISO
# date/datetime (2024-01-01[ 12:30[:00]]), dotted/slashed/dashed short-year
# or long-year (12.04.26, 04/12/2026, 12-04-26), or year-first slash/dot
# (2026/04/12). Deliberately does NOT match a bare run of digits (e.g. a
# plain numeric ID like "12345") — a date needs at least one separator.
_DATE_LIKE_PATTERN = re.compile(
    r"""^\s*(
        \d{4}-\d{1,2}-\d{1,2}([ T]\d{1,2}:\d{2}(:\d{2})?)?
        |\d{1,2}[./-]\d{1,2}[./-]\d{2,4}
        |\d{4}[./]\d{1,2}[./]\d{1,2}
    )\s*$""",
    re.VERBOSE,
)

_DEFAULT_SAMPLE_SIZE = 20
_DEFAULT_HIT_THRESHOLD = 0.8


def is_date_like_series(
    series: pd.Series | None,
    sample_size: int = _DEFAULT_SAMPLE_SIZE,
    hit_threshold: float = _DEFAULT_HIT_THRESHOLD,
) -> bool:
    """True when at least ``hit_threshold`` of a ``sample_size`` sample of
    ``series``'s non-null values are date-shaped (regex) AND parse cleanly
    via :func:`pandas.to_datetime`.

    A cheap, deterministic value-based check — never a guess from the
    column's name, never an LLM call. ``None``/empty/all-null input is "no
    signal", not a false positive: returns ``False``.
    """
    if series is None:
        return False
    sample = series.dropna().astype(str).head(sample_size)
    if sample.empty:
        return False
    shaped = sample[sample.map(lambda v: bool(_DATE_LIKE_PATTERN.match(v)))]
    if shaped.empty:
        return False
    parsed = pd.to_datetime(shaped, errors="coerce", format="mixed")
    hit_rate = parsed.notna().sum() / len(sample)
    return bool(hit_rate >= hit_threshold)
