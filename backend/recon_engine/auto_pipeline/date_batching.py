"""Date-aligned streaming-batch planning for the Auto pipeline.

Replaces the old year-window batching (``value_pairing/batching.py``, which
only ever sliced already-fully-extracted, in-memory Series) with a plan built
BEFORE any full extraction happens: a cheap, paginated, single-column pull of
just the date field from both connectors gives the distinct-date union AND
each date's per-side row count, which is enough to cut record-count-bounded
batches without ever pulling full rows up front.

A single date is NEVER split across batches — this is what makes the plan
lossless: every record that could possibly match another (date is part of the
business key) is guaranteed to land in the same batch, and a date present on
only one side still gets its own slot in the union (surfaces as Missing-in-
Target/Extra-in-Target later, never silently dropped).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import pandas as pd

DEFAULT_RECORD_THRESHOLD = 50_000
DEFAULT_MAX_DATES_PER_BATCH = 200


class _ColumnFetcher(Protocol):
    def preview_column(
        self, entity_name: str, field: str, date_filter: tuple[Any, Any] | None = None
    ) -> pd.Series: ...


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


def fetch_date_column(
    client: _ColumnFetcher,
    entity_name: str,
    date_field: str,
    date_filter: tuple[Any, Any] | None = None,
) -> pd.Series:
    """Thin wrapper over a metadata-service client's ``preview_column`` — the
    cheap, paginated, single-column pull used to build the date union."""
    return client.preview_column(entity_name, date_field, date_filter=date_filter)


def _normalized_date_counts(dates: pd.Series) -> pd.Series:
    """Per-normalized-calendar-day row counts, unparseable/missing dropped.

    Parsed with the EXACT ``dd.mm.yyyy`` format the connectors always
    normalize OData dates to (see ``odata_utils.sap_odata_date_to_ddmmyyyy``)
    — never the bare dateutil-guessing parser, which silently transposes
    day/month for any date where both are <=12 (dayfirst is ambiguous without
    an explicit format). Getting this wrong here would send the WRONG
    ``$filter`` date range to the connector for that batch (see
    ``odata_utils.to_odata_datetime_literal``, fed straight from
    ``DateBatch.start_date``/``end_date`` below).
    """
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
