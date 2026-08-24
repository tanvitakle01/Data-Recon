"""Lightweight corroboration signal — a narrow, reusable precursor to the
future full confidence-scoring system (cross-checking a proposed pairing
against real record-level agreement is explicitly deferred there; this is
just enough to break a tie between competing candidates now, without
throwing that later work away).

Used ONLY when a source value has more than one plausible candidate target
(see ``pipeline.pair_values``) — a sole candidate (identity-only or
transform-only) never calls this, so the common, unambiguous case stays free
of the extra pass over the data.
"""

from __future__ import annotations

import pandas as pd


def _dates_for_key(keys: pd.Series, dates: pd.Series, key_value: str) -> set:
    mask = keys.astype(str) == key_value
    parsed = pd.to_datetime(dates[mask], errors="coerce").dropna()
    return set(parsed.dt.normalize())


def corroboration_overlap(
    *,
    source_keys: pd.Series,
    source_dates: pd.Series | None,
    source_value: str,
    target_keys: pd.Series,
    target_dates: pd.Series | None,
    target_value: str,
) -> bool | None:
    """Whether any row for ``source_value`` shares a date with any row for
    ``target_value``.

    ``None`` means NO SIGNAL — either date column is unavailable, or one side
    has no parseable dates for this specific value — and must never be read
    as a negative signal (that would unfairly penalize sparse data). Only a
    real, positive overlap counts as corroboration.
    """
    if source_dates is None or target_dates is None:
        return None
    source_dates_for_value = _dates_for_key(source_keys, source_dates, source_value)
    target_dates_for_value = _dates_for_key(target_keys, target_dates, target_value)
    if not source_dates_for_value or not target_dates_for_value:
        return None
    return not source_dates_for_value.isdisjoint(target_dates_for_value)


def corroboration_evidence(
    *,
    source_keys: pd.Series,
    source_dates: pd.Series | None,
    source_value: str,
    target_keys: pd.Series,
    target_dates: pd.Series | None,
    target_value: str,
) -> tuple[bool, bool, bool]:
    """Like :func:`corroboration_overlap`, but returns the three components
    separately — ``(source_seen, target_seen, overlap)`` — instead of
    collapsing "no signal" and "no overlap" into a single ``None``.

    Used by the streaming batch orchestrator (``auto_pipeline.date_batching``
    et al.), which only ever sees ONE batch's slice of both Series at a time:
    ``source_seen``/``target_seen`` (did THIS batch have any dated row for
    the value at all) let the caller OR-accumulate evidence correctly across
    batches (see ``storage.corroboration_store``) — a plain ``None`` return
    would be ambiguous about which side (if either) actually had evidence
    this batch.
    """
    if source_dates is None or target_dates is None:
        return False, False, False
    source_dates_for_value = _dates_for_key(source_keys, source_dates, source_value)
    target_dates_for_value = _dates_for_key(target_keys, target_dates, target_value)
    source_seen = bool(source_dates_for_value)
    target_seen = bool(target_dates_for_value)
    overlap = (
        source_seen and target_seen
        and not source_dates_for_value.isdisjoint(target_dates_for_value)
    )
    return source_seen, target_seen, overlap
