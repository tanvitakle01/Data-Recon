"""Distinct-date-union batch partitioning for the value-pairing pipeline.

Replaces the old year-range partitioning with the SAME algorithm the Auto
pipeline uses to stream row-level extraction (see
``recon_engine.date_batch_planning.plan_batches``): a batch is cut every
``DEFAULT_MAX_DATES_PER_BATCH`` distinct calendar dates from the UNION of
source and target dates (a date present on both sides still counts once), or
``DEFAULT_RECORD_THRESHOLD`` combined records, whichever comes first — never
mid-date. Packing far more distinct values into each value-pairing batch than
a 1-year window typically could directly cuts per-run LLM call volume.

:func:`build_batches` is the one that actually gates work: its
``(label, source_mask, target_mask)`` triples come from ONE shared batch plan
computed over BOTH sides together — a source and target record dated the same
day always land in the same labeled batch. ``source_mask`` is what
``pipeline.pair_values`` slices the SOURCE side with to select each batch's
work. ``target_mask`` is used ONLY for progress reporting/labeling
(``BatchProgress.target_candidate_count``) — never as a filter on which
target values a batch can match against. The target side's actual matching
pool stays a single full-dataset pass (see ``pipeline.pair_values``) because a
value's source and target records can carry different dates — scoping target
*matching* to the same batch as its proposing source records would silently
drop real pairings whenever the two sides' dates for the same value don't
happen to land in the same batch. Batching is purely a performance/
checkpointing/progress concern (smaller per-batch LLM payloads, retryable/
observable per batch) and must never gate whether a value CAN be matched.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.excel_comparator.core.date_alignment import parse_dates
from backend.recon_engine.date_batch_planning import (
    DEFAULT_MAX_DATES_PER_BATCH,
    DEFAULT_RECORD_THRESHOLD,
    plan_batches,
)

__all__ = [
    "DEFAULT_MAX_DATES_PER_BATCH",
    "DEFAULT_RECORD_THRESHOLD",
    "BatchProgress",
    "build_batches",
]


@dataclass(frozen=True)
class BatchProgress:
    """Reported to an optional ``on_batch`` callback after each batch resolves."""

    field_pair: str  # e.g. "Material -> PRDID"
    batch_index: int  # 0-based
    batch_count: int
    batch_label: str  # a date/date-range label, or "Undated" / "All records"
    target_candidate_count: int | None = None  # distinct target values whose
    # own date falls in this batch's window — display-only; a value missing
    # from this count is NOT excluded from matching (see module docstring).
    # None when the target has no dated rows in this window.


def _all_records_batch(
    source_series: pd.Series, target_series: pd.Series
) -> list[tuple[str, pd.Series, pd.Series]]:
    return [
        (
            "All records",
            pd.Series(True, index=source_series.index),
            pd.Series(True, index=target_series.index),
        )
    ]


def build_batches(
    *,
    source_series: pd.Series,
    target_series: pd.Series,
    source_dates: pd.Series | None,
    target_dates: pd.Series | None,
    max_dates_per_batch: int = DEFAULT_MAX_DATES_PER_BATCH,
    record_threshold: int = DEFAULT_RECORD_THRESHOLD,
) -> list[tuple[str, pd.Series, pd.Series]]:
    """``(label, source_mask, target_mask)`` triples, oldest date-window
    first, "Undated" last — both masks over their own series' own index.

    Degrades to a single "All records" triple (covering every row on both
    sides) when neither side has any usable/parseable date, so an absent date
    column never blocks pairing; it only forfeits the batching/checkpointing
    benefit for this call.
    """
    if source_dates is None and target_dates is None:
        return _all_records_batch(source_series, target_series)

    empty_source = pd.Series([pd.NaT] * len(source_series), index=source_series.index)
    empty_target = pd.Series([pd.NaT] * len(target_series), index=target_series.index)
    parsed_source = parse_dates(source_dates) if source_dates is not None else empty_source
    parsed_target = parse_dates(target_dates) if target_dates is not None else empty_target
    parsed_source = parsed_source.dt.normalize()
    parsed_target = parsed_target.dt.normalize()

    date_batches = plan_batches(
        parsed_source, parsed_target,
        record_threshold=record_threshold, max_dates_per_batch=max_dates_per_batch,
    )
    if not date_batches:
        return _all_records_batch(source_series, target_series)

    result: list[tuple[str, pd.Series, pd.Series]] = []
    for b in date_batches:
        start, end = pd.Timestamp(b.start_date), pd.Timestamp(b.end_date)
        result.append((b.label, parsed_source.between(start, end), parsed_target.between(start, end)))

    # A side with NO date column at all (``*_dates is None``) is a different
    # case from one WITH a date column that just has some unparseable/missing
    # values in it: the former must never itself trigger an "Undated" batch —
    # ``empty_source``/``empty_target`` above are a plan-building convenience
    # (plan_batches needs two real series), not a claim that every row on
    # that side is genuinely undated. Otherwise a caller that only has one
    # side's dates (e.g. a resumed/partial call) would get a phantom
    # "Undated" batch covering 100% of the dateless side for no reason.
    undated_source = parsed_source.isna() if source_dates is not None else pd.Series(False, index=source_series.index)
    undated_target = parsed_target.isna() if target_dates is not None else pd.Series(False, index=target_series.index)
    if undated_source.any() or undated_target.any():
        result.append(("Undated", undated_source, undated_target))

    return result
