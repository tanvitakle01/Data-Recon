"""Drill-through record queries: given the one `filter` spec a facts payload
hands back verbatim (see `facts.py`), return the matching subset of
records — sort, page, and CSV export all live here so every level
(break-rate, hotspot, variance bin, unmapped mapping) drills through the
same way, down to the underlying source/target row values already carried
on each "All Records"-shaped row.
"""

from __future__ import annotations

from io import StringIO
from typing import Any

import pandas as pd

from backend.recon_engine.insights.normalize import NormalizedRecon


def _representative(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    if len(cols) == 1:
        return df[cols[0]]
    return df[cols].bfill(axis=1).iloc[:, 0]


def _row_magnitude(df: pd.DataFrame, delta_columns: list[str]) -> pd.Series:
    if not delta_columns or df.empty:
        return pd.Series(0.0, index=df.index, dtype=float)
    numeric = df[delta_columns].apply(pd.to_numeric, errors="coerce")
    return numeric.abs().sum(axis=1, skipna=True)


def _apply_filter(normalized: NormalizedRecon, filter_spec: dict[str, Any]) -> pd.DataFrame:
    df = normalized.records_df
    kind = (filter_spec or {}).get("kind")
    if not kind:
        return df

    if kind == "status":
        return df[df["__status__"] == filter_spec.get("value")]

    if kind == "dimension":
        cols = normalized.dimension_columns.get(filter_spec.get("field") or "", [])
        if not cols or df.empty:
            return df.iloc[0:0]
        values = _representative(df, cols).fillna("(blank)").astype(str)
        return df[values == str(filter_spec.get("value"))]

    if kind == "varianceBin":
        if not normalized.delta_columns or df.empty:
            return df.iloc[0:0]
        magnitude = _row_magnitude(df, normalized.delta_columns)
        lo, hi = filter_spec.get("min"), filter_spec.get("max")
        return df[(magnitude >= lo) & (magnitude <= hi)]

    if kind == "dateOutsideWindow":
        from backend.recon_engine.insights.facts import date_series_by_side

        series = date_series_by_side(df, normalized.dimension_columns, normalized.compare_pairs)
        if series is None:
            return df.iloc[0:0]
        src_dates, tgt_dates = series
        side = filter_spec.get("side")
        if side == "source":
            tgt_valid = tgt_dates.dropna()
            if tgt_valid.empty:
                return df.iloc[0:0]
            tgt_min, tgt_max = tgt_valid.min(), tgt_valid.max()
            return df[src_dates.notna() & ((src_dates < tgt_min) | (src_dates > tgt_max))]
        if side == "target":
            src_valid = src_dates.dropna()
            if src_valid.empty:
                return df.iloc[0:0]
            src_min, src_max = src_valid.min(), src_valid.max()
            return df[tgt_dates.notna() & ((tgt_dates < src_min) | (tgt_dates > src_max))]
        return df.iloc[0:0]

    if kind == "mappingUnpaired":
        # Mapping Details rows for this field — a distinct-value-level drill,
        # one level above per-record rows, since a mapping row is per source
        # value, not per record.
        return normalized.mapping_df[normalized.mapping_df["Mapping"] == filter_spec.get("mapping")]

    return df.iloc[0:0]


def filter_records(
    normalized: NormalizedRecon,
    filter_spec: dict[str, Any] | None,
    *,
    sort: str | None = None,
    sort_dir: str = "asc",
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    df = _apply_filter(normalized, filter_spec or {})
    if sort and sort in df.columns:
        df = df.sort_values(sort, ascending=(sort_dir != "desc"), na_position="last")
    total_matched = int(len(df))
    start = max(0, (page - 1) * max(1, page_size))
    page_df = df.iloc[start : start + max(1, page_size)]
    safe = page_df.astype(object).where(pd.notna(page_df), None)
    columns = [c for c in safe.columns if c != "field_diffs"]
    return {"columns": columns, "rows": safe[columns].to_dict(orient="records"), "totalMatched": total_matched}


def records_to_csv(normalized: NormalizedRecon, filter_spec: dict[str, Any] | None) -> str:
    df = _apply_filter(normalized, filter_spec or {})
    columns = [c for c in df.columns if c != "field_diffs"]
    buf = StringIO()
    df[columns].to_csv(buf, index=False)
    return buf.getvalue()
