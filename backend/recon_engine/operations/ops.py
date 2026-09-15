"""Manual, deterministic implementations of every allow-listed operation.

Each function here is hand-written and unit-tested. The LLM may only *reference*
these by name in a contract; it can never define new ones. If a contract names
an operation not implemented here, Gate 1 rejects it.

Two callable shapes exist:

* transform / filter / aggregate ops:  ``fn(df, field, params) -> DataFrame``
* compare ops:                          ``fn(src, tgt, params) -> BoolSeries``
                                        (True == the two values match)
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from backend.recon_engine.key_normalization import fit_group_key
from backend.recon_engine.models.contract import AggregationType, MEASURE_AGGREGATIONS

# ── date format translation ──────────────────────────────────────────────────
# Human tokens (DD.MM.YYYY) -> strftime. Order matters: longer/less-ambiguous
# tokens first. "MM" is month, lowercase "mm" is minutes.
_FMT_TOKENS: list[tuple[str, str]] = [
    ("YYYY", "%Y"),
    ("YY", "%y"),
    ("MM", "%m"),
    ("DD", "%d"),
    ("HH", "%H"),
    ("mm", "%M"),
    ("SS", "%S"),
]


def format_to_strftime(fmt: str) -> str:
    out = fmt
    for token, code in _FMT_TOKENS:
        out = out.replace(token, code)
    return out


# ── transform ops ──────────────────────────────────────────────────────────

def identity_cast_string(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Cast a column to string, preserving nulls as NaN."""
    out = df.copy()
    col = out[field]
    out[field] = col.where(col.isna(), col.astype(str))
    return out


def trim_string(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Strip leading/trailing whitespace from a string column."""
    out = df.copy()
    col = out[field]
    out[field] = col.where(col.isna(), col.astype(str).str.strip())
    return out


def numeric_cast(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Coerce a column to numeric; unparseable values become NaN."""
    out = df.copy()
    out[field] = pd.to_numeric(out[field], errors="coerce")
    return out


def date_parse(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Parse a date column from ``source_format`` and reformat to ``canonical_format``.

    Unparseable values become NaN (surfaced by Gate 2 as a low parse rate).
    """
    out = df.copy()
    src_fmt = format_to_strftime(params["source_format"])
    canon_fmt = format_to_strftime(params.get("canonical_format", "YYYY-MM-DD"))
    parsed = pd.to_datetime(out[field], format=src_fmt, errors="coerce")
    out[field] = parsed.dt.strftime(canon_fmt)
    return out


# Pandas period-alias per granularity — the SAME vocabulary the structured
# ``aggregation_rules`` period-aggregations use (see
# ``engine.executor._PERIOD_FREQ`` / ``AggregationType.GROUP_BY_*``), so a date
# bucketed here and one bucketed via an aggregation rule land on the same
# period-start convention.
_DATE_BUCKET_FREQ: dict[str, str] = {
    "day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y",
}


def date_bucket(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Floor/ceil a date column to a period boundary, emitting canonical
    YYYY-MM-DD.

    ``granularity`` is one of day/week/month/quarter/year; ``anchor`` is
    'start' (default — the period's first day, e.g. 2025-08-19 -> 2025-08-01
    for month) or 'end' (the period's last day, e.g. -> 2025-08-31).
    Unparseable values become null. This is the general, standalone form of
    the period-bucketing the structured ``aggregation_rules``
    ``group_by_*``/``AggregationType`` family applies during aggregation —
    use this one when a bucketed date is needed as an ordinary value
    transform (e.g. before a filter or comparison), not as a grouping key.
    """
    out = df.copy()
    granularity = str(params["granularity"]).strip().lower()
    anchor = str(params.get("anchor", "start")).strip().lower()
    freq = _DATE_BUCKET_FREQ[granularity]

    dt = pd.to_datetime(out[field], errors="coerce")
    period = dt.dt.to_period(freq)
    boundary = period.dt.start_time if anchor != "end" else period.dt.end_time.dt.normalize()
    out[field] = boundary.dt.strftime("%Y-%m-%d").where(dt.notna(), None)
    return out


def rename_field(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Rename column ``field`` to ``params['to']``.

    NOTE: ``rename_field`` only relabels a column — it NEVER changes the values
    inside it. A business rule that means "modify the value" (add a prefix,
    strip zeros, replace text, …) must compile to one of the value ops below,
    not to a rename. Renaming a business-key field also removes the old name
    from the shadow schema, which Gate 1 rejects.
    """
    return df.rename(columns={field: params["to"]})


# ── value-transform ops ──────────────────────────────────────────────────────
# Row-preserving edits to the VALUES of a single string/numeric column. Each one
# leaves NaN untouched (nulls stay null) so downstream key building and null
# checks behave predictably. These are the executable form of the user's
# "Transformation Rules" and of a mapping sheet's transformation text — the
# whole point is that such rules become operations here, never contract notes.

def _str_where_notna(col: pd.Series, transformed: pd.Series) -> pd.Series:
    """Return ``transformed`` where ``col`` is non-null, else the original NaN."""
    return col.where(col.isna(), transformed)


def _map_notna(col: pd.Series, func) -> pd.Series:
    """Apply a string->string ``func`` to each non-null value; nulls pass through.

    Guards a pandas quirk where ``col.astype(str).map(func)`` can still hand
    ``func`` a raw float NaN for a null cell instead of a stringified one
    (observed with Arrow-backed string dtypes) — ``func`` here only ever sees
    real strings, never a NaN it would have to guard against itself.
    """
    return col.map(lambda v: func(str(v)) if pd.notna(v) else v)


def prepend_prefix(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Prepend a fixed prefix to every non-null value (e.g. '5006' -> 'PL5006')."""
    out = df.copy()
    prefix = str(params["value"])
    col = out[field]
    out[field] = _str_where_notna(col, prefix + col.astype(str))
    return out


def append_suffix(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Append a fixed suffix to every non-null value (e.g. '5006' -> '5006@S21400')."""
    out = df.copy()
    suffix = str(params["value"])
    col = out[field]
    out[field] = _str_where_notna(col, col.astype(str) + suffix)
    return out


_NUMERIC_RUN = re.compile(r"(\d+)")


def remove_leading_zeros(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Strip leading zeros from the first embedded numeric run, leaving any
    non-digit prefix/suffix untouched ('005006' -> '5006', 'FG0006' -> 'FG6').

    ``min_width`` (default 1) is the floor the numeric run is stripped down
    to, e.g. ``min_width=2`` turns '0006' into '06' rather than '6' — some
    zero-padded codes (e.g. 'FG0006' <-> 'FG06') strip down to a minimum
    width, not to bare significant digits. An all-zero run becomes as many
    zeros as ``min_width`` requires (default: a single '0'). A value with no
    digits at all is left unchanged.
    """
    out = df.copy()
    col = out[field]
    min_width = max(1, int(params.get("min_width", 1)))

    def _strip(value: str) -> str:
        match = _NUMERIC_RUN.search(value)
        if not match:
            return value
        digits = match.group(1)
        stripped = digits.lstrip("0")
        if len(stripped) < min_width:
            stripped = digits[-min_width:] if len(digits) >= min_width else digits
        return value[: match.start()] + stripped + value[match.end() :]

    out[field] = _map_notna(col, _strip)
    return out


def pad_leading_zeros(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Left-pad the first embedded numeric run with zeros to ``width``, leaving
    any non-digit prefix/suffix untouched ('5006' -> '005006' at width=6,
    'FG6' -> 'FG006' at width=3). Inverse of :func:`remove_leading_zeros`. A
    numeric run already at or beyond ``width`` is left unchanged; a value with
    no digits at all is left unchanged.
    """
    out = df.copy()
    col = out[field]
    width = int(params["width"])

    def _pad(value: str) -> str:
        match = _NUMERIC_RUN.search(value)
        if not match:
            return value
        digits = match.group(1)
        padded = digits.rjust(width, "0")
        return value[: match.start()] + padded + value[match.end() :]

    out[field] = _map_notna(col, _pad)
    return out


def replace_value(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Literal substring replace of ``from`` with ``to`` ('N01-FG01' -> 'T01-FG01').

    Not a regex — the ``from`` text is matched literally. Use ``value_mapping``
    for whole-value lookups and ``regex_replace`` for pattern-based edits.
    """
    out = df.copy()
    frm, to = str(params["from"]), str(params["to"])
    col = out[field]
    out[field] = _str_where_notna(col, col.astype(str).str.replace(frm, to, regex=False))
    return out


def uppercase(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Upper-case a string column."""
    out = df.copy()
    col = out[field]
    out[field] = _str_where_notna(col, col.astype(str).str.upper())
    return out


def lowercase(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Lower-case a string column."""
    out = df.copy()
    col = out[field]
    out[field] = _str_where_notna(col, col.astype(str).str.lower())
    return out


def substring(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Slice each value by 0-based ``start`` and optional ``length``."""
    out = df.copy()
    start = int(params.get("start", 0))
    length = params.get("length")
    col = out[field]
    as_str = col.astype(str)
    sliced = as_str.str.slice(start, start + int(length)) if length is not None else as_str.str.slice(start)
    out[field] = _str_where_notna(col, sliced)
    return out


def regex_replace(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Regex substitute ``pattern`` -> ``replacement``.

    The pattern/replacement are *data* consumed by pandas' vectorised string
    replace — never executed as code. Behaviour is fully deterministic.
    """
    out = df.copy()
    pattern = str(params["pattern"])
    replacement = str(params["replacement"])
    col = out[field]
    out[field] = _str_where_notna(col, col.astype(str).str.replace(pattern, replacement, regex=True))
    return out


def concat_fields(df: pd.DataFrame, field: str | None, params: dict[str, Any]) -> pd.DataFrame:
    """Join several columns into a single ``into`` column with a ``separator``.

    Nulls are treated as empty strings for the join so a composite key is not
    polluted with the literal text 'nan'. ``into`` may be a new column (Gate 1
    tracks it as added so later ops and business keys can reference it).
    """
    out = df.copy()
    cols = list(params["fields"])
    sep = str(params.get("separator", ""))
    into = params.get("into") or field
    parts = [out[c].where(out[c].notna(), "").astype(str) for c in cols]
    joined = parts[0]
    for p in parts[1:]:
        joined = joined.str.cat(p, sep=sep)
    out[into] = joined
    return out


def decimal_round(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Coerce to numeric and round to ``decimals`` places (default 0)."""
    out = df.copy()
    decimals = int(params.get("decimals", 0))
    out[field] = pd.to_numeric(out[field], errors="coerce").round(decimals)
    return out


def null_to_default(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Replace null/blank values with ``default``."""
    out = df.copy()
    default = params["default"]
    col = out[field]
    blank = col.isna() | col.astype(str).str.strip().eq("")
    out[field] = col.mask(blank, default)
    return out


def value_mapping(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Whole-value lookup replacement via ``mapping`` (a from->to dict).

    Unmapped non-null values are left unchanged unless ``default`` is supplied,
    in which case they take the default. Keys are matched as strings.
    """
    out = df.copy()
    mapping = {str(k): v for k, v in dict(params["mapping"]).items()}
    has_default = "default" in params
    default = params.get("default")
    col = out[field]

    def _map(v: Any) -> Any:
        if pd.isna(v):
            return v
        key = str(v)
        if key in mapping:
            return mapping[key]
        return default if has_default else v

    out[field] = col.map(_map)
    return out


def _condition_mask(col: pd.Series, condition: str, params: dict[str, Any]) -> pd.Series:
    """Row mask for the conditional_* ops. Always excludes nulls."""
    non_null = col.notna()
    if condition == "numeric":
        return non_null & pd.to_numeric(col, errors="coerce").notna()
    if condition == "non_numeric":
        return non_null & pd.to_numeric(col, errors="coerce").isna()
    if condition == "matches":
        pattern = str(params.get("pattern", ""))
        return non_null & col.astype(str).str.match(pattern)
    # "non_empty" (default): any non-null, non-blank value.
    return non_null & col.astype(str).str.strip().ne("")


def conditional_prefix(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Prepend ``value`` only to rows satisfying ``condition``.

    ``condition`` is one of 'numeric', 'non_numeric', 'non_empty' (default), or
    'matches' (with a ``pattern``). Example: "Add prefix PL when numeric".
    """
    out = df.copy()
    prefix = str(params["value"])
    col = out[field]
    mask = _condition_mask(col, params.get("condition", "non_empty"), params)
    out.loc[mask, field] = prefix + col[mask].astype(str)
    return out


def conditional_suffix(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Append ``value`` only to rows satisfying ``condition`` (see conditional_prefix)."""
    out = df.copy()
    suffix = str(params["value"])
    col = out[field]
    mask = _condition_mask(col, params.get("condition", "non_empty"), params)
    out.loc[mask, field] = col[mask].astype(str) + suffix
    return out


def split_field(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Split each value of ``field`` on ``separator`` and keep the part at the
    0-based ``index``, writing into ``into`` (defaults to ``field`` itself).

    An out-of-range index yields null for that row; nulls stay null. ``into``
    may be a new column (Gate 1 tracks it as added, like ``concat_fields``).
    """
    out = df.copy()
    sep = str(params["separator"])
    index = int(params["index"])
    into = params.get("into") or field
    col = out[field]

    def _part(v: Any) -> Any:
        if pd.isna(v):
            return v
        parts = str(v).split(sep)
        return parts[index] if -len(parts) <= index < len(parts) else None

    out[into] = col.map(_part)
    return out


def convert_uom(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Convert a numeric field's unit of measure by a fixed ``factor``.

    ``operation`` is 'multiply' (default) or 'divide' — e.g. cases→eaches with
    factor 12 (multiply), or grams→kilograms with factor 1000 (divide). Optional
    ``decimals`` rounds the result. Non-numeric values become null (a genuine
    signal, surfaced by Gate 2). The conversion is fixed data, never code.
    """
    out = df.copy()
    factor = float(params["factor"])
    operation = str(params.get("operation", "multiply")).lower()
    numeric = pd.to_numeric(out[field], errors="coerce")
    converted = numeric / factor if operation == "divide" else numeric * factor
    decimals = params.get("decimals")
    if decimals is not None:
        converted = converted.round(int(decimals))
    out[field] = converted
    return out


def calculated_column(df: pd.DataFrame, field: str | None, params: dict[str, Any]) -> pd.DataFrame:
    """Compute a new column ``into`` from a safe, allow-listed ``expression``.

    The expression (e.g. ``ABS(PLNMG - DEMANDQTY)``) references existing columns
    and a fixed function set. It is parsed to an AST and evaluated
    deterministically by :mod:`~backend.recon_engine.operations.safe_expr` —
    NEVER Python ``eval``/``exec``. Gate 1 validates the expression against the
    live schema before this ever runs.
    """
    from backend.recon_engine.operations.safe_expr import eval_expression

    out = df.copy()
    into = params["into"]
    out[into] = eval_expression(str(params["expression"]), out)
    return out


# ``run_date`` is never authored on a contract — the executor injects it as
# ``params["_run_date"]`` at EXECUTION time only, for the operations declared
# ``needs_run_date`` in the registry (see ``OperationSpec``). Gate 1 validates
# the stored contract's authored params, which never include this key.
_WEEKDAY_NAMES: dict[str, int] = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def resolve_weekday(value: Any) -> int:
    """A weekday name (any case, e.g. ``"Saturday"``) or an already-numeric
    0-6 (Mon-Sun) value -> its 0-6 index. Public: shared with
    ``engine.anchor_inference``, which has to interpret a
    ``relative_date_reassign`` operation's own ``weekday_exception`` param the
    SAME way this operation does, to invert it back to a run_date."""
    if isinstance(value, int):
        return value
    return _WEEKDAY_NAMES[str(value).strip().lower()]


def relative_date_reassign(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Replace a date with an offset from run_date when a condition holds,
    else pass the value through unchanged.

    ``date_condition`` ('lt' | 'gt' | 'eq') compares ``field`` against
    ``compare_to`` — 'run_date' (default) or another column name. When it
    holds, ``field`` is replaced with ``run_date + offset_days`` (canonical
    YYYY-MM-DD). Optional ``weekday_exception``
    ({"on_weekday": <name or 0-6 Mon-Sun>, "offset_days": <int>}) overrides
    ``offset_days`` when run_date itself falls on that weekday — e.g. a
    past-due date rolls forward by 1 day normally, but by 2 days when
    run_date is a Saturday. Rows where ``field``/``compare_to`` don't parse as
    dates are left unchanged (the condition can't be decided).
    """
    out = df.copy()
    run_date = pd.Timestamp(params["_run_date"]).normalize()
    compare_to = str(params.get("compare_to") or "run_date")
    condition = str(params["date_condition"]).strip().lower()
    offset_days = int(params["offset_days"])
    weekday_exception = params.get("weekday_exception")

    dt = pd.to_datetime(out[field], errors="coerce")
    other = run_date if compare_to == "run_date" else pd.to_datetime(out[compare_to], errors="coerce")

    if condition == "lt":
        mask = dt < other
    elif condition == "gt":
        mask = dt > other
    elif condition == "eq":
        mask = dt == other
    else:
        raise ValueError(f"relative_date_reassign: unknown date_condition '{condition}'")
    mask &= dt.notna()
    if compare_to != "run_date":
        mask &= other.notna()

    effective_offset = offset_days
    if weekday_exception:
        if not isinstance(weekday_exception, dict) or "on_weekday" not in weekday_exception or "offset_days" not in weekday_exception:
            raise ValueError(
                "relative_date_reassign: 'weekday_exception' must be an object with "
                "'on_weekday' and 'offset_days', e.g. "
                '{"on_weekday": "saturday", "offset_days": 2}.'
            )
        if run_date.weekday() == resolve_weekday(weekday_exception["on_weekday"]):
            effective_offset = int(weekday_exception["offset_days"])

    replacement = (run_date + pd.Timedelta(days=effective_offset)).strftime("%Y-%m-%d")
    out.loc[mask, field] = replacement
    return out


# ── filter ops ───────────────────────────────────────────────────────────────

def reject_null(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Drop rows where ``field`` is null or an empty/whitespace-only string."""
    col = df[field]
    blank = col.isna() | col.astype(str).str.strip().eq("")
    return df.loc[~blank].copy()


def date_window_filter(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Keep rows whose date in ``field`` falls within an offset window of
    run_date: ``[run_date + lower_offset_days, run_date + upper_offset_days]``.

    Either bound may be omitted for an open-ended window (e.g. only
    ``lower_offset_days=-30`` keeps everything from 30 days ago onward).
    Unparseable dates are dropped (they can't be evaluated against the
    window). Unlike ``exclude_value``/``include_value`` (literal values),
    this filters relative to the run-time anchor, not a fixed date.
    """
    run_date = pd.Timestamp(params["_run_date"]).normalize()
    dt = pd.to_datetime(df[field], errors="coerce")
    mask = dt.notna()
    lower = params.get("lower_offset_days")
    upper = params.get("upper_offset_days")
    if lower is not None:
        mask &= dt >= run_date + pd.Timedelta(days=int(lower))
    if upper is not None:
        mask &= dt <= run_date + pd.Timedelta(days=int(upper))
    return df.loc[mask].copy()


def exclude_value(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Drop rows where ``field`` equals any of ``params['values']``."""
    values = [str(v) for v in params["values"]]
    return df.loc[~df[field].astype(str).isin(values)].copy()


def include_value(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Keep only rows where ``field`` equals one of ``params['values']``.

    The inclusion counterpart to :func:`exclude_value` — for selection filters
    such as "sales org = 5875" that keep a subset rather than drop one.
    """
    values = [str(v) for v in params["values"]]
    return df.loc[df[field].astype(str).isin(values)].copy()


# ── aggregate ops ──────────────────────────────────────────────────────────
# Every op here groups on the CANONICAL form of its ``by`` columns
# (``key_normalization.fit_group_key``) rather than on the raw values, because
# raw values compare by Python type: a column Excel stored partly as text and
# partly as numbers arrives as a mix of "2000" and 2000, which pandas puts in
# two different groups. The reconciler's join canonicalizes, so it would then
# see one business key carrying two rows and silently keep only the first —
# the other group's measures would vanish from the run's totals. Grouping the
# way the join compares is what keeps a sum whole.
#
# The GROUPED values themselves are left exactly as they were: each group
# emits the first original value it saw for the column, so a zero-padded
# material code stays zero-padded in the output even though it grouped
# canonically.

def _grouped_by_canonical_key(
    df: pd.DataFrame, by: list[str], agg_spec: dict[str, str]
) -> pd.DataFrame:
    """Group ``df`` on the canonical form of ``by`` and apply ``agg_spec``.

    Returns the ``by`` columns (original values, first per group) followed by
    the aggregated ones — the same shape a plain ``groupby(by).agg(...)``
    returns, minus the type-sensitivity.
    """
    frame = df.reset_index(drop=True)
    keys = fit_group_key(frame, by)(frame)
    key_cols = list(keys.columns)
    tmp = pd.concat([frame, keys], axis=1)
    # "first" carries each grouping column's original value through; listing
    # them before the measures keeps the column order groupby(by) produced.
    spec = {col: "first" for col in by if col not in agg_spec}
    spec.update(agg_spec)
    result = tmp.groupby(key_cols, as_index=False, dropna=False).agg(spec)
    return result.drop(columns=key_cols)


def group_by(df: pd.DataFrame, field: str | None, params: dict[str, Any]) -> pd.DataFrame:
    """Collapse to one row per unique combination of ``params['by']`` columns."""
    by = list(params["by"])
    duplicated = fit_group_key(df, by)(df).duplicated(keep="first")
    return df[~duplicated.to_numpy()].copy()


def sum_aggregate(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Group by ``params['by']`` and sum ``field``; keep only key + summed columns."""
    by = list(params["by"])
    numeric = pd.to_numeric(df[field], errors="coerce")
    tmp = df[by].copy()
    tmp[field] = numeric
    return _grouped_by_canonical_key(tmp, by, {field: "sum"})


def deduplicate(df: pd.DataFrame, field: str | None, params: dict[str, Any]) -> pd.DataFrame:
    """Drop duplicate rows keyed on the ``by`` columns, keeping ``keep``.

    ``keep`` is 'first' (default) or 'last'. Row-reducing, so it is an AGGREGATE
    op — the executor collapses lineage of every duplicate onto the kept row
    (identical grouping key handling to the other aggregates)."""
    by = list(params["by"])
    keep = str(params.get("keep", "first")).lower()
    if keep not in ("first", "last"):
        keep = "first"
    duplicated = fit_group_key(df, by)(df).duplicated(keep=keep)
    return df[~duplicated.to_numpy()].copy()


# The measure-aggregation vocabulary (sum/count/average/min/max) — same enum
# `aggregation_rules` uses, so a field/func picked in one part of the UI means
# the same thing everywhere.
AGGREGATE_FUNCS: frozenset[str] = frozenset(a.value for a in MEASURE_AGGREGATIONS)
_AGG_PANDAS_FUNC: dict[str, str] = {
    AggregationType.SUM.value: "sum",
    AggregationType.COUNT.value: "count",
    AggregationType.AVERAGE.value: "mean",
    AggregationType.MIN.value: "min",
    AggregationType.MAX.value: "max",
    AggregationType.FIRST.value: "first",
}
_NUMERIC_AGG_FUNCS = {
    AggregationType.SUM.value,
    AggregationType.AVERAGE.value,
    AggregationType.MIN.value,
    AggregationType.MAX.value,
}


def aggregate_group(df: pd.DataFrame, field: str | None, params: dict[str, Any]) -> pd.DataFrame:
    """Group by ``params['by']`` (any number of columns) and apply one or more
    aggregations in a single step — "Aggregate & Group": each entry in
    ``params['aggregations']`` is ``{"field": <column>, "func":
    "sum"|"count"|"average"|"min"|"max"|"first"}``. Any number of ``by``
    columns and any number of measures are supported in one call — e.g. group
    by product+plant+customer+month while summing quantity AND averaging
    price in the same step. One function per field; a field named twice keeps
    the last entry. ``first`` passes a non-measured column (e.g. a
    description) through from an arbitrary row in the group rather than
    dropping it.

    Lineage is preserved automatically and unconditionally: every AGGREGATE-
    kind operation (this one included) is wrapped by
    ``engine.executor._apply_aggregate``, which records every contributing
    raw source row id against the collapsed group row — never opt-in, never
    skippable by a param here.
    """
    by = list(params["by"])
    tmp = df.copy()
    agg_spec: dict[str, str] = {}
    for a in params["aggregations"]:
        col = a["field"]
        func_name = str(a["func"])
        pandas_func = _AGG_PANDAS_FUNC[func_name]
        if func_name in _NUMERIC_AGG_FUNCS:
            tmp[col] = pd.to_numeric(tmp[col], errors="coerce")
        agg_spec[col] = pandas_func
    return _grouped_by_canonical_key(tmp, by, agg_spec)


# ── compare ops (used by the reconciler, not the shadow builder) ─────────────

def _normalise(series: pd.Series, options: dict[str, Any]) -> pd.Series:
    s = series.astype(str)
    if options.get("trim_whitespace", True):
        s = s.str.strip()
    if options.get("case_insensitive", True):
        s = s.str.casefold()
    return s


def _repr_equal(a: pd.Series, b: pd.Series) -> pd.Series:
    """Numeric equality that canonicalises IEEE-754 representation error only.

    Two numbers produced by float arithmetic (a UOM conversion, calculated
    column, or aggregate sum) can differ in their last binary digit — e.g.
    ``0.1 + 0.2`` yields ``0.30000000000000004`` — even when they are logically
    identical. A raw ``==`` flags those as mismatches. The ``rtol``/``atol`` here
    are orders of magnitude tighter than any real quantity delta, so genuine
    differences (100 vs 0, 100 vs 100.001) still count as unequal. This is
    representation canonicalisation, NOT a business tolerance.
    """
    close = np.isclose(
        a.to_numpy(dtype=float), b.to_numpy(dtype=float), rtol=1e-9, atol=1e-12
    )
    return pd.Series(close, index=a.index)


def exact_match(src: pd.Series, tgt: pd.Series, params: dict[str, Any]) -> pd.Series:
    """Element-wise equality. Numeric where both sides parse as numbers, else
    normalised string equality. NaN == NaN is treated as a match."""
    options = params.get("options", {})
    src_num = pd.to_numeric(src, errors="coerce")
    tgt_num = pd.to_numeric(tgt, errors="coerce")
    both_numeric = src_num.notna() & tgt_num.notna()

    result = pd.Series(False, index=src.index)
    result[both_numeric] = _repr_equal(src_num[both_numeric], tgt_num[both_numeric])

    non_numeric = ~both_numeric
    if non_numeric.any():
        both_null = src.isna() & tgt.isna()
        norm_src = _normalise(src, options)
        norm_tgt = _normalise(tgt, options)
        result[non_numeric] = (norm_src[non_numeric] == norm_tgt[non_numeric]) | both_null[non_numeric]
    return result


def tolerance_match(src: pd.Series, tgt: pd.Series, params: dict[str, Any]) -> pd.Series:
    """Numeric equality within an absolute ``tolerance``.

    Rows where either side is non-numeric yield False (a genuine exception the
    reconciler surfaces), except NaN==NaN which is a match.
    """
    tol = float(params.get("tolerance", 0.0))
    src_num = pd.to_numeric(src, errors="coerce")
    tgt_num = pd.to_numeric(tgt, errors="coerce")
    # OR in representation-equality so a 0 (or tiny) tolerance still absorbs
    # IEEE-754 float noise rather than flagging logically-equal values.
    within = ((src_num - tgt_num).abs() <= tol) | _repr_equal(src_num, tgt_num)
    both_null = src.isna() & tgt.isna()
    return (within & src_num.notna() & tgt_num.notna()) | both_null
