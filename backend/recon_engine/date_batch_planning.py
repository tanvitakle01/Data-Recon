"""Distinct-date-union batch planning — shared by the Auto pipeline's
streaming extraction (``auto_pipeline.date_batching``) and the value-pairing
pipeline's LLM-payload batching (``value_pairing.batching``).

Builds an ordered batch plan over the UNION of distinct calendar dates from
both a source and a target date column: a single date is NEVER split across
batches, and a date present on only one side still occupies its own slot in
the union (contributes 0 from the other side) rather than being silently
skipped. A batch is cut once either ``max_dates_per_batch`` distinct dates or
``record_threshold`` combined records have accumulated, whichever comes
first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

DEFAULT_RECORD_THRESHOLD = 50_000
DEFAULT_MAX_DATES_PER_BATCH = 4000


@dataclass(frozen=True)
class DateBatch:
    """One record-count-bounded, date-aligned window of the streaming plan."""

    batch_index: int  # 0-based
    batch_count: int
    start_date: str  # "YYYY-MM-DD", inclusive
    end_date: str  # "YYYY-MM-DD", inclusive
    date_count: int
    estimated_record_count: int

    @property
    def label(self) -> str:
        if self.start_date == self.end_date:
            return self.start_date
        return f"{self.start_date} to {self.end_date}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_index": self.batch_index,
            "batch_count": self.batch_count,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "date_count": self.date_count,
            "estimated_record_count": self.estimated_record_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DateBatch":
        return cls(
            batch_index=data["batch_index"],
            batch_count=data["batch_count"],
            start_date=data["start_date"],
            end_date=data["end_date"],
            date_count=data["date_count"],
            estimated_record_count=data["estimated_record_count"],
        )


def _normalized_date_counts(dates: pd.Series) -> pd.Series:
    """Per-normalized-calendar-day row counts, unparseable/missing dropped.

    An already-``datetime64``-typed series (pre-parsed by the caller — e.g.
    ``auto_pipeline.nodes`` for an "upload" side, or ``value_pairing.batching``
    for Manual mode, both via ``excel_comparator.core.date_alignment.
    parse_dates``, since uploaded/manual data carries no guaranteed format) is
    normalized as-is. Anything else is parsed with the EXACT ``dd.mm.yyyy``
    format the connectors always normalize OData dates to (see
    ``odata_utils.sap_odata_date_to_ddmmyyyy``) — never the bare
    dateutil-guessing parser, which silently transposes day/month for any
    date where both are <=12 (dayfirst is ambiguous without an explicit
    format). Getting this wrong here would send the WRONG ``$filter`` date
    range to the connector for that batch (see ``odata_utils.
    to_odata_datetime_literal``, fed straight from ``DateBatch.start_date``/
    ``end_date`` below) when this plan drives a connector fetch.
    """
    if pd.api.types.is_datetime64_any_dtype(dates):
        parsed = dates.dropna()
    else:
        parsed = pd.to_datetime(dates, format="%d.%m.%Y", errors="coerce").dropna()
    if parsed.empty:
        return pd.Series([], dtype="int64")
    return parsed.dt.normalize().value_counts()


def plan_batches(
    source_dates: pd.Series,
    target_dates: pd.Series,
    *,
    record_threshold: int = DEFAULT_RECORD_THRESHOLD,
    max_dates_per_batch: int = DEFAULT_MAX_DATES_PER_BATCH,
) -> list[DateBatch]:
    """Builds the ordered, record-count-bounded batch plan over the UNION of
    distinct dates from both sides.

    Walks the sorted union oldest-first, accumulating ``source_count +
    target_count`` per date, and cuts a batch at the next date boundary once
    either the record threshold or ``max_dates_per_batch`` is reached — a date
    is never split mid-batch. A date present on only one side contributes only
    that side's count (the other side is 0), so it still occupies its own
    slot in the union rather than being silently skipped.
    """
    source_counts = _normalized_date_counts(source_dates)
    target_counts = _normalized_date_counts(target_dates)

    all_dates = sorted(set(source_counts.index) | set(target_counts.index))
    if not all_dates:
        return []

    windows: list[tuple[pd.Timestamp, pd.Timestamp, int, int]] = []
    cur_start: pd.Timestamp | None = None
    cur_end: pd.Timestamp | None = None
    cur_records = 0
    cur_dates = 0

    for date in all_dates:
        date_records = int(source_counts.get(date, 0)) + int(target_counts.get(date, 0))
        would_exceed_records = cur_records > 0 and cur_records + date_records > record_threshold
        would_exceed_dates = cur_dates >= max_dates_per_batch
        if cur_start is not None and (would_exceed_records or would_exceed_dates):
            windows.append((cur_start, cur_end, cur_dates, cur_records))
            cur_start = None

        if cur_start is None:
            cur_start = date
            cur_records = 0
            cur_dates = 0

        cur_end = date
        cur_records += date_records
        cur_dates += 1

    if cur_start is not None:
        windows.append((cur_start, cur_end, cur_dates, cur_records))

    batch_count = len(windows)
    return [
        DateBatch(
            batch_index=i,
            batch_count=batch_count,
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
            date_count=date_count,
            estimated_record_count=records,
        )
        for i, (start, end, date_count, records) in enumerate(windows)
    ]
