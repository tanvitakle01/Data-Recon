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

from typing import Any

import pandas as pd

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


def remove_leading_zeros(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Strip leading zeros ('005006' -> '5006'). An all-zero value becomes '0'."""
    out = df.copy()
    col = out[field]
    stripped = col.astype(str).str.lstrip("0")
    stripped = stripped.mask(stripped.eq(""), "0")
    out[field] = _str_where_notna(col, stripped)
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


# ── filter ops ───────────────────────────────────────────────────────────────

def reject_null(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Drop rows where ``field`` is null or an empty/whitespace-only string."""
    col = df[field]
    blank = col.isna() | col.astype(str).str.strip().eq("")
    return df.loc[~blank].copy()


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

def group_by(df: pd.DataFrame, field: str | None, params: dict[str, Any]) -> pd.DataFrame:
    """Collapse to one row per unique combination of ``params['by']`` columns."""
    by = list(params["by"])
    return df.drop_duplicates(subset=by, keep="first").copy()


def sum_aggregate(df: pd.DataFrame, field: str, params: dict[str, Any]) -> pd.DataFrame:
    """Group by ``params['by']`` and sum ``field``; keep only key + summed columns."""
    by = list(params["by"])
    numeric = pd.to_numeric(df[field], errors="coerce")
    tmp = df[by].copy()
    tmp[field] = numeric
    return tmp.groupby(by, as_index=False, dropna=False)[field].sum()


def deduplicate(df: pd.DataFrame, field: str | None, params: dict[str, Any]) -> pd.DataFrame:
    """Drop duplicate rows keyed on the ``by`` columns, keeping ``keep``.

    ``keep`` is 'first' (default) or 'last'. Row-reducing, so it is an AGGREGATE
    op — the executor collapses lineage of every duplicate onto the kept row
    (identical grouping key handling to the other aggregates)."""
    by = list(params["by"])
    keep = str(params.get("keep", "first")).lower()
    if keep not in ("first", "last"):
        keep = "first"
    return df.drop_duplicates(subset=by, keep=keep).copy()


# ── compare ops (used by the reconciler, not the shadow builder) ─────────────

def _normalise(series: pd.Series, options: dict[str, Any]) -> pd.Series:
    s = series.astype(str)
    if options.get("trim_whitespace", True):
        s = s.str.strip()
    if options.get("case_insensitive", True):
        s = s.str.casefold()
    return s


def exact_match(src: pd.Series, tgt: pd.Series, params: dict[str, Any]) -> pd.Series:
    """Element-wise equality. Numeric where both sides parse as numbers, else
    normalised string equality. NaN == NaN is treated as a match."""
    options = params.get("options", {})
    src_num = pd.to_numeric(src, errors="coerce")
    tgt_num = pd.to_numeric(tgt, errors="coerce")
    both_numeric = src_num.notna() & tgt_num.notna()

    result = pd.Series(False, index=src.index)
    result[both_numeric] = src_num[both_numeric] == tgt_num[both_numeric]

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
    within = (src_num - tgt_num).abs() <= tol
    both_null = src.isna() & tgt.isna()
    return (within & src_num.notna() & tgt_num.notna()) | both_null
