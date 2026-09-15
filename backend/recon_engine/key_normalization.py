"""Canonicalization of key column VALUES — for the reconciler's join, and for
every GROUPING key an aggregate step forms on the way to it.

A business-key field (a date, or a numeric identifier) can be serialized
differently on the source and target side of a reconciliation — ISO
``2026-09-14`` vs ``9/4/2026``, or ``786293.0`` (a numeric column read from
Excel) vs ``786293`` (text) — even when the underlying values are logically
identical. :func:`~backend.recon_engine.engine.reconciler._build_key` used to
compare these with a plain trim/casefold string equality, which makes the
join fail 100% of the time for a field pair that merely disagrees on format,
regardless of whether every other part of the reconciliation (filters,
transforms, aggregation) is correct.

The same disagreement happens WITHIN one column: ``pandas`` reads an Excel
sheet with ``dtype=object``, so a column where some cells were typed as text
and some as numbers arrives as a mix of ``"2000"`` and ``2000``. Those two
compare unequal to ``groupby``, so an aggregate splits one business key into
two groups — and the join, which canonicalizes, then sees one key with two
rows and silently drops one (``drop_duplicates(keep="first")``), taking its
quantity out of the total. Grouping therefore uses exactly the key equality
the join uses, via :func:`fit_group_key`: whatever the join would treat as
one key must aggregate as one group, or rows go missing between the two.

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

from typing import Any, Callable

import pandas as pd

from backend.recon_engine.date_detection import (
    detect_date_format,
    is_date_like_series,
    parse_with_format,
    strftime_format,
)

_NUMERIC_SAMPLE_SIZE = 20
_NUMERIC_HIT_THRESHOLD = 0.8

# A fitted canonicalizer: classify one column once, then re-express any series
# of that column (the full frame, or the shorter frame an aggregate produced
# from it) in the same canonical form.
KeyCanonicalizer = Callable[[pd.Series], pd.Series]

# Prefix for the hidden grouping-key columns :func:`fit_group_key` builds. They
# never reach a result — every caller drops them after grouping.
GROUP_KEY_PREFIX = "__group_key_"


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


def fit_key_canonicalizer(series: pd.Series) -> KeyCanonicalizer:
    """Classify ``series`` ONCE and return a canonicalizer for that column.

    * Date-like (:func:`is_date_like_series`): every value that parses as a
      date becomes ISO ``YYYY-MM-DD``, regardless of the column's original
      textual format (``M/D/YYYY``, ``DD.MM.YYYY``, zero-padded or not).
      Values that don't parse are left as-is (the column was only *mostly*
      date-shaped). The format is read off ``series`` here and then reused —
      never re-detected — so applying the canonicalizer to a subset can't
      silently pick a different day/month order than the full column did.
    * Numeric-like (:func:`_is_numeric_like_series`): every value that parses
      as a number becomes :func:`_canonical_numeric_string`. Non-numeric
      values (e.g. an alpha-suffixed code in an otherwise-numeric ID column)
      are left as-is.
    * Otherwise: values are returned unchanged.

    Fitting is separate from applying because an aggregate step has to
    canonicalize the same column twice — once on the rows going in, once on
    the collapsed rows coming out — and the two must agree even though the
    second frame holds one row per group and could well classify differently
    on its own.
    """
    if is_date_like_series(series):
        spec = detect_date_format(series)
        fmt = strftime_format(spec) if spec is not None else None

        def canonicalize_dates(values: pd.Series) -> pd.Series:
            parsed = parse_with_format(values, fmt)
            return parsed.dt.strftime("%Y-%m-%d").where(parsed.notna(), values)

        return canonicalize_dates

    if _is_numeric_like_series(series):

        def canonicalize_numbers(values: pd.Series) -> pd.Series:
            numeric = pd.to_numeric(values, errors="coerce")
            canonical = numeric.map(
                lambda v: _canonical_numeric_string(v) if pd.notna(v) else None
            )
            return canonical.where(numeric.notna(), values)

        return canonicalize_numbers

    return lambda values: values


def canonicalize_key_column(series: pd.Series) -> pd.Series:
    """``series`` re-expressed in a fixed canonical form when it looks like a
    date or a numeric identifier; otherwise unchanged — see
    :func:`fit_key_canonicalizer` for what each shape becomes.

    Detection and canonicalization both run independently per column/side —
    the caller never needs the two sides to agree on which original format
    they use, only on the fixed canonical one this converges them onto.
    """
    if series.empty:
        return series
    return fit_key_canonicalizer(series)(series)


def normalize_key_scalar(value: Any, options: dict[str, Any] | None = None) -> str:
    """The string form two key values are compared as: nulls become ``""``,
    and (by default) whitespace is trimmed and case folded.

    Shared by the reconciler's join key and by grouping, so "same key" means
    one thing across the engine.
    """
    options = options or {}
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value)
    if options.get("trim_whitespace", True):
        text = text.strip()
    if options.get("case_insensitive", True):
        text = text.casefold()
    return text


def fit_group_key(df: pd.DataFrame, by: list[str]) -> Callable[[pd.DataFrame], pd.DataFrame]:
    """Fit the grouping key for columns ``by`` on ``df``, returning a callable
    that maps a frame to a frame of hidden canonical key columns.

    Group on the result instead of on ``by`` directly and two rows the join
    would treat as one key — ``"2000"`` and ``2000`` in one Excel column,
    ``786293`` and ``786293.0``, ``9/4/2026`` and ``2026-09-04`` — land in one
    group, which is the only way an aggregate's output can survive the join
    intact (see this module's header).

    The canonicalizers are fitted on ``df`` and can then be applied to the
    aggregated frame as well, so a group and its own result row always compute
    the same key however the aggregate reordered or collapsed its rows.

    Key normalization deliberately uses :func:`normalize_key_scalar`'s
    DEFAULTS rather than the contract's ``options``: an op has no access to
    them, and grouping that is coarser than the join merely merges two groups,
    while grouping that is finer hands the join duplicate keys — which it
    resolves by dropping rows.
    """
    # A ``by`` column that isn't there is a bug in the caller, and silently
    # dropping it from the key would collapse unrelated rows into one group —
    # so let the missing-column KeyError surface, as ``groupby(by)`` did.
    canonicalizers = {col: fit_key_canonicalizer(df[col]) for col in by}
    names = {col: f"{GROUP_KEY_PREFIX}{i}__" for i, col in enumerate(by)}

    def group_key_frame(frame: pd.DataFrame) -> pd.DataFrame:
        data = {
            names[col]: canonicalizers[col](frame[col]).map(normalize_key_scalar)
            for col in by
        }
        return pd.DataFrame(data, index=frame.index)

    return group_key_frame
