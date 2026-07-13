from __future__ import annotations

from typing import Any, Optional

import pandas as pd

DATE_CANDIDATES: list[str] = [
    "reqdlvdate",
    "keyfiguredate",
    "deliverydate",
    "delivery date",
    "postingdate",
    "documentdate",
    "requesteddeliverydate",
    "period",
    "date",
]


def _normalize_col(col: str) -> str:
    return str(col).strip().lower().replace(" ", "").replace("_", "")


def parse_dates(series: pd.Series) -> pd.Series:
    """Parse a column into datetimes robustly across common upload formats.

    Excel/pandas typically hand back either native datetime values or ISO
    strings (YYYY-MM-DD). Forcing ``dayfirst=True`` on those swaps month and
    day (e.g. 2026-01-05 -> 2026-05-01), which silently corrupts date-range
    alignment. So we parse ISO/native dates first and only fall back to
    day-first parsing when it actually rescues more values (genuine DD/MM/YYYY
    string data).
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return series

    default = pd.to_datetime(series, errors="coerce")
    # If everything parsed, the default (ISO-aware) interpretation is correct.
    if default.notna().all():
        return default

    dayfirst = pd.to_datetime(series, errors="coerce", dayfirst=True)
    # Prefer day-first only when it parses strictly more values than the default.
    if dayfirst.notna().sum() > default.notna().sum():
        return dayfirst
    return default


def detect_date_column(df: pd.DataFrame) -> Optional[str]:
    if df is None or df.empty:
        return None

    cols = list(df.columns)
    if not cols:
        return None

    wanted = [_normalize_col(c) for c in DATE_CANDIDATES]
    norm_map = {c: _normalize_col(c) for c in cols}

    for c, n in norm_map.items():
        for w in wanted:
            if w in n:
                return c
    return None


def date_range(df: pd.DataFrame, col: str) -> Optional[tuple[pd.Timestamp, pd.Timestamp]]:
    if df is None or col not in df.columns:
        return None

    parsed = parse_dates(df[col])
    parsed = parsed.dropna()
    if parsed.empty:
        return None

    return parsed.min(), parsed.max()


def filter_to_window(df: pd.DataFrame, col: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    if df is None or col not in df.columns:
        return df

    parsed = parse_dates(df[col])
    keep_mask = parsed.isna() | ((parsed >= start) & (parsed <= end))
    return df.loc[keep_mask].reset_index(drop=True)


def _iso(ts: pd.Timestamp) -> str:
    return ts.date().isoformat()


def build_alignment(source_df: pd.DataFrame, target_df: pd.DataFrame) -> dict[str, Any]:
    source_col = detect_date_column(source_df)
    target_col = detect_date_column(target_df)

    source_span = date_range(source_df, source_col) if source_col else None
    target_span = date_range(target_df, target_col) if target_col else None

    source_total = int(len(source_df)) if source_df is not None else 0
    target_total = int(len(target_df)) if target_df is not None else 0

    overlap: Optional[tuple[pd.Timestamp, pd.Timestamp]] = None
    if source_span and target_span:
        overlap_start = max(source_span[0], target_span[0])
        overlap_end = min(source_span[1], target_span[1])
        if overlap_start <= overlap_end:
            overlap = (overlap_start, overlap_end)

    source_included = source_total
    target_included = target_total
    if overlap and source_col:
        source_included = int(len(filter_to_window(source_df, source_col, *overlap)))
    if overlap and target_col:
        target_included = int(len(filter_to_window(target_df, target_col, *overlap)))

    return {
        "source_date_column": source_col,
        "target_date_column": target_col,
        "source_range": {"start": _iso(source_span[0]), "end": _iso(source_span[1])} if source_span else None,
        "target_range": {"start": _iso(target_span[0]), "end": _iso(target_span[1])} if target_span else None,
        "overlap": {"start": _iso(overlap[0]), "end": _iso(overlap[1])} if overlap else None,
        "has_overlap": overlap is not None,
        "source_total": source_total,
        "source_included": source_included,
        "source_excluded": source_total - source_included,
        "target_total": target_total,
        "target_included": target_included,
        "target_excluded": target_total - target_included,
    }
