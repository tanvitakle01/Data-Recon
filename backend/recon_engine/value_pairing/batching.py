"""Year-range batch partitioning for the value-pairing pipeline's SOURCE side.

Splits the source dataset into consecutive N-year windows anchored at the
earliest parseable date on the source's own date column — e.g. earliest year
2021, a 2-year window -> "2021-2022", "2023-2024", ... — processed oldest
first so library reuse (see ``pipeline.pair_values``) accumulates
predictably across a rerun. Records with a missing/unparseable date form one
extra trailing "Undated" batch, processed last.

Deliberately SOURCE-only: the target side's distinct-value set stays a single
full-dataset pass (see ``pipeline.pair_values``) because a value's source and
target records can carry different dates — scoping target extraction to the
same calendar window as its proposing batch would silently drop real
pairings whenever the two sides' dates for the same value don't happen to
fall in the same window. Batching here is purely a performance/checkpointing
concern (smaller per-batch LLM payloads, retryable/observable per batch) and
must never gate whether a value CAN be matched.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

DEFAULT_WINDOW_YEARS = 2


@dataclass(frozen=True)
class BatchProgress:
    """Reported to an optional ``on_batch`` callback after each batch resolves."""

    field_pair: str  # e.g. "Material -> PRDID"
    batch_index: int  # 0-based
    batch_count: int
    batch_label: str  # "2021-2022", or "Undated" / "All records"


def build_source_batches(
    *,
    source_series: pd.Series,
    source_dates: pd.Series | None,
    window_years: int = DEFAULT_WINDOW_YEARS,
) -> list[tuple[str, pd.Series]]:
    """(label, boolean mask) pairs over ``source_series``'s own index, oldest
    year-range first, "Undated" last.

    Degrades to a single "All records" batch — covering every row — when no
    date column is available at all, so an absent date never blocks pairing;
    it only forfeits the batching/checkpointing benefit for this call.
    """
    if source_dates is None:
        return [("All records", pd.Series(True, index=source_series.index))]

    years = pd.to_datetime(source_dates, errors="coerce").dt.year
    real_years = years.dropna()
    has_undated = bool(years.isna().any())
    if real_years.empty:
        return [("All records", pd.Series(True, index=source_series.index))]

    window_years = max(1, window_years)
    min_year = int(real_years.min())
    max_year = int(real_years.max())

    batches: list[tuple[str, pd.Series]] = []
    start = min_year
    while start <= max_year:
        end = start + window_years - 1
        label = str(start) if start == end else f"{start}-{end}"
        batches.append((label, years.between(start, end)))
        start = end + 1
    if has_undated:
        batches.append(("Undated", years.isna()))
    return batches
