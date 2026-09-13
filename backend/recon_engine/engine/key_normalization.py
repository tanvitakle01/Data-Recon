"""Canonicalization of business-key column VALUES before the reconciler's join.

A business-key field (a date, or a numeric identifier) can be serialized
differently on the source and target side of a reconciliation — ISO
``2026-09-14`` vs ``9/4/2026``, or ``786293.0`` (a numeric column read from
Excel) vs ``786293`` (text) — even when the underlying values are logically
identical. :func:`~backend.recon_engine.engine.reconciler._build_key` used to
compare these with a plain trim/casefold string equality, which makes the
join fail 100% of the time for a field pair that merely disagrees on format,
regardless of whether every other part of the reconciliation (filters,
transforms, aggregation) is correct.

``canonicalize_key_column`` fixes this WITHOUT any per-contract configuration
and WITHOUT assuming either side's format: each side is independently
classified from its OWN sampled values (never the column name, never an
LLM, never a hardcoded "the source is always X" assumption) and, when it
looks like a date or a numeric identifier, re-expressed in one fixed
internal canonical form. Two columns using different original formats still
converge on the same canonical string as long as they represent the same
underlying value — which is all the join needs.

A value that doesn't fit the detected shape (an alpha-suffixed material code
sitting in an otherwise-numeric ID column, an unparseable date) is left
exactly as-is and falls through to the existing string comparison — this
never invents or forces a value it can't confidently reshape.
"""

from __future__ import annotations

import pandas as pd

from backend.recon_engine.date_detection import is_date_like_series, parse_date_series

_NUMERIC_SAMPLE_SIZE = 20
_NUMERIC_HIT_THRESHOLD = 0.8


def _is_numeric_like_series(
    series: pd.Series,
    sample_size: int = _NUMERIC_SAMPLE_SIZE,
    hit_threshold: float = _NUMERIC_HIT_THRESHOLD,
) -> bool:
    """True when most of a sample of ``series``'s non-null values parse as a
    plain number.

    Mirrors :func:`is_date_like_series`'s sample-and-threshold shape: a
    handful of non-numeric outliers (e.g. a material code with an alpha
    suffix in an otherwise-numeric column) don't disqualify the column —
    they simply aren't reshaped, and fall back to plain string comparison
    for those specific values.
    """
    if series is None:
        return False
    sample = series.dropna().astype(str).head(sample_size)
    if sample.empty:
        return False
    hit_rate = pd.to_numeric(sample, errors="coerce").notna().sum() / len(sample)
    return bool(hit_rate >= hit_threshold)


def _canonical_numeric_string(value: float) -> str:
    """A stable string form for a numeric key value: a bare integer when the
    value is whole (``786293.0`` -> ``"786293"``), else a fixed-precision
    decimal with trailing zeros trimmed (``5.100000`` -> ``"5.1"``) — applied
    identically regardless of which side originally carried the extra
    decimal point/precision.
    """
    if value == int(value):
        return str(int(value))
    text = f"{value:.10f}".rstrip("0").rstrip(".")
    return text


def canonicalize_key_column(series: pd.Series) -> pd.Series:
    """Return ``series`` re-expressed in a fixed canonical form when it looks
    like a date or a numeric identifier; otherwise return it unchanged.

    * Date-like (:func:`is_date_like_series`): every value that parses as a
      date becomes ISO ``YYYY-MM-DD``, regardless of the column's original
      textual format (``M/D/YYYY``, ``DD.MM.YYYY``, zero-padded or not).
      Values that don't parse are left as-is (the column was only *mostly*
      date-shaped).
    * Numeric-like (:func:`_is_numeric_like_series`): every value that parses
      as a number becomes :func:`_canonical_numeric_string`. Non-numeric
      values (e.g. an alpha-suffixed code in an otherwise-numeric ID column)
      are left as-is.
    * Otherwise: returned unchanged.

    Detection and canonicalization both run independently per column/side —
    the caller never needs the two sides to agree on which original format
    they use, only on the fixed canonical one this converges them onto.
    """
    if series.empty:
        return series
    if is_date_like_series(series):
        parsed = parse_date_series(series)
        canonical = parsed.dt.strftime("%Y-%m-%d")
        return canonical.where(parsed.notna(), series)
    if _is_numeric_like_series(series):
        numeric = pd.to_numeric(series, errors="coerce")
        canonical = numeric.map(lambda v: _canonical_numeric_string(v) if pd.notna(v) else None)
        return canonical.where(numeric.notna(), series)
    return series
