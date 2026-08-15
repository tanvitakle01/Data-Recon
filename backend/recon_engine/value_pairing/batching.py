"""Year-range batch partitioning for the value-pairing pipeline.

Splits a dataset into consecutive N-year windows anchored at the earliest
parseable date on its own date column — e.g. earliest year 2021, a 1-year
window -> "2021", "2022", ... — processed oldest first so library reuse
(see ``pipeline.pair_values``) accumulates predictably across a rerun.
Records with a missing/unparseable date form one extra trailing "Undated"
batch, processed last.

:func:`build_source_batches` is the one that actually gates work: its
(label, mask) pairs slice the SOURCE side per batch in ``pipeline.pair_values``.
:func:`build_target_batches` computes the identical year-window partition
over the TARGET side, but is used ONLY for progress reporting/labeling
(``BatchProgress.target_candidate_count``) — never as a filter on which
target values a batch can match against. The target side's actual
matching pool stays a single full-dataset pass (see ``pipeline.pair_values``)
because a value's source and target records can carry different dates —
scoping target *matching* to the same calendar window as its proposing
batch would silently drop real pairings whenever the two sides' dates for
the same value don't happen to fall in the same window. Batching is purely
a performance/checkpointing/progress concern (smaller per-batch LLM
payloads, retryable/observable per batch) and must never gate whether a
value CAN be matched.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

DEFAULT_WINDOW_YEARS = 1


@dataclass(frozen=True)
class BatchProgress:
    """Reported to an optional ``on_batch`` callback after each batch resolves."""

    field_pair: str  # e.g. "Material -> PRDID"
    batch_index: int  # 0-based
    batch_count: int
    batch_label: str  # "2021", or "Undated" / "All records"
    target_candidate_count: int | None = None  # distinct target values whose
    # own date falls in this batch's calendar window — display-only; a value
    # missing from this count is NOT excluded from matching (see module
    # docstring). None when the target has no dated rows in this window.


def _year_windows(
    dates: pd.Series | None,
    index: pd.Index,
    window_years: int,
) -> list[tuple[str, pd.Series]]:
    """Shared windowing math for both the source and target sides: parses
    ``dates`` to calendar years and partitions ``index`` into consecutive
    ``window_years``-sized windows, oldest first, with unparseable/missing
    dates in one trailing "Undated" batch. Degrades to a single "All
    records" batch when ``dates`` is absent or has no parseable values."""
    if dates is None:
        return [("All records", pd.Series(True, index=index))]

    years = pd.to_datetime(dates, errors="coerce").dt.year
    real_years = years.dropna()
    has_undated = bool(years.isna().any())
    if real_years.empty:
        return [("All records", pd.Series(True, index=index))]

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
    return _year_windows(source_dates, source_series.index, window_years)


def build_target_batches(
    *,
    target_series: pd.Series,
    target_dates: pd.Series | None,
    window_years: int = DEFAULT_WINDOW_YEARS,
) -> list[tuple[str, pd.Series]]:
    """Same year-window partition as :func:`build_source_batches`, computed
    over the TARGET side. Display/progress-reporting ONLY — see this
    module's docstring. Never pass this into a matching path; the target
    values a batch can match against must always stay the full,
    unsliced set.
    """
    return _year_windows(target_dates, target_series.index, window_years)
