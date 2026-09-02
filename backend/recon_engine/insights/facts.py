"""Pure fact computation over a `NormalizedRecon` — counts, rankings, and
distributions only. No thresholds, health scores, or generated language:
every number is a direct count/sum/percentage off the records themselves,
and every entry carries a `filter` spec the frontend replays verbatim
against `/insights/records` for drill-through.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend.recon_engine.insights.normalize import (
    STATUS_LABELS,
    STATUS_MATCH,
    STATUS_MISSING_IN_SOURCE,
    STATUS_MISSING_IN_TARGET,
    STATUS_ORDER,
    NormalizedRecon,
)

_HOTSPOT_TOP_N = 5
_UNMAPPED_TOP_N = 5


def _abs_variance_per_row(df: pd.DataFrame, delta_columns: list[str]) -> pd.Series:
    if not delta_columns or df.empty:
        return pd.Series(0.0, index=df.index, dtype=float)
    numeric = df[delta_columns].apply(pd.to_numeric, errors="coerce")
    return numeric.abs().sum(axis=1, skipna=True)


def _break_rate_summary(df: pd.DataFrame, abs_variance: pd.Series, delta_columns: list[str]) -> dict[str, Any]:
    total = int(len(df))
    counts = df["__status__"].value_counts().to_dict() if total else {}
    results = []
    for status in STATUS_ORDER:
        count = int(counts.get(status, 0))
        pct = round(count / total * 100.0, 1) if total else 0.0
        results.append(
            {
                "key": status,
                "label": STATUS_LABELS[status],
                "count": count,
                "pct": pct,
                "filter": {"kind": "status", "value": status},
            }
        )
    net_delta = 0.0
    if delta_columns and not df.empty:
        numeric = df[delta_columns].apply(pd.to_numeric, errors="coerce")
        net_delta = round(float(numeric.sum(skipna=True).sum()), 2)
    total_abs_variance = round(float(abs_variance.sum()), 2) if not df.empty else 0.0
    return {
        "total": total,
        "results": results,
        "netDelta": net_delta,
        "totalAbsoluteVariance": total_abs_variance,
    }


def _representative(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    """One value per row across a dimension's candidate columns (e.g. a
    value-mapped key's "X (Original)" + "Y (Paired)" pair) — the first
    non-null column wins, same source-preferred-over-target convention as
    `service._unified`."""
    if len(cols) == 1:
        return df[cols[0]]
    return df[cols].bfill(axis=1).iloc[:, 0]


def _hotspots(df: pd.DataFrame, abs_variance: pd.Series, dimension_columns: dict[str, list[str]]) -> list[dict[str, Any]]:
    sections = []
    for label, cols in dimension_columns.items():
        if df.empty:
            sections.append({"label": label, "field": label, "rows": []})
            continue
        values = _representative(df, cols).fillna("(blank)").astype(str)
        is_break = df["__status__"] != STATUS_MATCH
        work = pd.DataFrame({"value": values.values, "is_break": is_break.values, "abs_variance": abs_variance.values})
        grouped = (
            work.groupby("value")
            .agg(breakCount=("is_break", "sum"), totalCount=("is_break", "count"), absQtyVariance=("abs_variance", "sum"))
            .reset_index()
        )
        grouped = grouped[grouped["breakCount"] > 0]
        grouped = grouped.sort_values(["breakCount", "absQtyVariance"], ascending=False).head(_HOTSPOT_TOP_N)
        rows = [
            {
                "value": r["value"],
                "breakCount": int(r["breakCount"]),
                "totalCount": int(r["totalCount"]),
                "absQtyVariance": round(float(r["absQtyVariance"]), 2),
                "filter": {"kind": "dimension", "field": label, "value": r["value"]},
            }
            for _, r in grouped.iterrows()
        ]
        sections.append({"label": label, "field": label, "rows": rows})
    return sections


def _variance_distribution(abs_variance: pd.Series) -> list[dict[str, Any]]:
    magnitudes = abs_variance[abs_variance > 0]
    if magnitudes.empty:
        return []
    try:
        binned = pd.qcut(magnitudes, q=4, duplicates="drop")
    except ValueError:
        binned = pd.cut(magnitudes, bins=1, include_lowest=True)
    grouped = magnitudes.groupby(binned, observed=True).agg(["count", "sum"])
    bins = []
    for i, (interval, row) in enumerate(grouped.iterrows()):
        bins.append(
            {
                "index": i,
                "min": round(float(interval.left), 2),
                "max": round(float(interval.right), 2),
                "count": int(row["count"]),
                "totalAbsVariance": round(float(row["sum"]), 2),
                "filter": {"kind": "varianceBin", "min": float(interval.left), "max": float(interval.right)},
            }
        )
    return bins


def _unmapped_by_field(mapping_df: pd.DataFrame) -> list[dict[str, Any]]:
    if mapping_df.empty or "Mapping" not in mapping_df.columns:
        return []
    rows = []
    for label, group in mapping_df.groupby("Mapping"):
        unpaired = int((group["Status"] == "Unpaired").sum())
        paired = int((group["Status"] == "Paired").sum())
        rows.append(
            {
                "label": label,
                "unpaired": unpaired,
                "paired": paired,
                "total": unpaired + paired,
                "filter": {"kind": "mappingUnpaired", "mapping": label},
            }
        )
    rows.sort(key=lambda r: r["unpaired"], reverse=True)
    return rows[:_UNMAPPED_TOP_N]


def date_series_by_side(
    df: pd.DataFrame, dimension_columns: dict[str, list[str]], compare_pairs: list[tuple[str, str]]
) -> tuple[pd.Series, pd.Series] | None:
    """The detected "Date" dimension's parsed values, split into the rows
    that actually carry a source-side date vs. a target-side date — shared
    by `_date_coverage` (below) and `query.py`'s ``dateOutsideWindow`` drill-
    through filter, so both agree on exactly the same two windows."""
    date_cols = dimension_columns.get("Date")
    if not date_cols or df.empty:
        return None

    pair = next((p for p in compare_pairs if p[0] in date_cols and p[1] in date_cols), None)
    if pair:
        sf, tf = pair
        src_dates = pd.to_datetime(df[sf], errors="coerce")
        tgt_dates = pd.to_datetime(df[tf], errors="coerce")
    else:
        col = date_cols[0]
        parsed = pd.to_datetime(df[col], errors="coerce")
        source_present = df["__status__"] != STATUS_MISSING_IN_SOURCE
        target_present = df["__status__"] != STATUS_MISSING_IN_TARGET
        src_dates = parsed.where(source_present)
        tgt_dates = parsed.where(target_present)
    return src_dates, tgt_dates


def _date_coverage(
    df: pd.DataFrame, dimension_columns: dict[str, list[str]], compare_pairs: list[tuple[str, str]]
) -> dict[str, Any] | None:
    series = date_series_by_side(df, dimension_columns, compare_pairs)
    if series is None:
        return None
    src_dates, tgt_dates = series
    src_dates, tgt_dates = src_dates.dropna(), tgt_dates.dropna()

    if src_dates.empty and tgt_dates.empty:
        return None

    src_min, src_max = (src_dates.min(), src_dates.max()) if not src_dates.empty else (None, None)
    tgt_min, tgt_max = (tgt_dates.min(), tgt_dates.max()) if not tgt_dates.empty else (None, None)

    source_outside_target_window = 0
    target_outside_source_window = 0
    if not src_dates.empty and tgt_min is not None:
        source_outside_target_window = int(((src_dates < tgt_min) | (src_dates > tgt_max)).sum())
    if not tgt_dates.empty and src_min is not None:
        target_outside_source_window = int(((tgt_dates < src_min) | (tgt_dates > src_max)).sum())

    return {
        "sourceMin": src_min.date().isoformat() if src_min is not None else None,
        "sourceMax": src_max.date().isoformat() if src_max is not None else None,
        "targetMin": tgt_min.date().isoformat() if tgt_min is not None else None,
        "targetMax": tgt_max.date().isoformat() if tgt_max is not None else None,
        "sourceDatesOutsideTargetWindow": source_outside_target_window,
        "targetDatesOutsideSourceWindow": target_outside_source_window,
        "sourceOutsideWindowFilter": {"kind": "dateOutsideWindow", "side": "source"},
        "targetOutsideWindowFilter": {"kind": "dateOutsideWindow", "side": "target"},
    }


def build_facts(normalized: NormalizedRecon) -> dict[str, Any]:
    df = normalized.records_df
    abs_variance = _abs_variance_per_row(df, normalized.delta_columns)
    return {
        "runId": normalized.run_id,
        "uploadId": normalized.upload_id,
        "breakRate": _break_rate_summary(df, abs_variance, normalized.delta_columns),
        "hotspots": _hotspots(df, abs_variance, normalized.dimension_columns),
        "varianceDistribution": _variance_distribution(abs_variance),
        "unmappedByField": _unmapped_by_field(normalized.mapping_df),
        "dateCoverage": _date_coverage(df, normalized.dimension_columns, normalized.compare_pairs),
    }
