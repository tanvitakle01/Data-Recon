"""Suspend/resume staleness fingerprint for one Auto-mode run's source/target.

Neither ``S4MetadataService`` nor ``IBPMetadataService`` exposes a generic
"last modified" signal (both are metadata-driven, no hardcoded per-connector
field assumptions — see ``auto_pipeline/nodes.py``'s module docstring), so the
cheap proxy used here is ``{row_count, max_date}`` per side: row count via one
``$inlinecount=allpages``/``$top=0`` call (``count_entity`` on each connector),
and the max value of the SAME business "date" field role already detected for
batch planning (reusing ``date_batching.fetch_date_column`` — no extra
resolution work, no new connector capability beyond the count). This catches
new/removed dated rows; it will not catch an in-place edit to a non-date field
on an already-extracted row.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend.recon_engine.auto_pipeline.date_batching import (
    client_for,
    entity_and_field_for_batch,
    fetch_date_column,
)
from backend.recon_engine.storage import snapshot_store


def _max_date(dates: pd.Series) -> str | None:
    # Same explicit dd.mm.yyyy format date_batching.py's own
    # _normalized_date_counts uses — never the bare dateutil guesser, which
    # silently transposes day/month for an ambiguous date.
    parsed = pd.to_datetime(dates, format="%d.%m.%Y", errors="coerce").dropna()
    return parsed.max().strftime("%Y-%m-%d") if not parsed.empty else None


def _capture_side(kind: str, spec: dict[str, Any], date_field: str) -> dict[str, Any]:
    if kind == "upload":
        # An ingested snapshot is immutable once created (already relied on
        # elsewhere — see shadow_store.create_shadow's raw_snapshot_hash), so
        # its own content hash IS the staleness signal: no live re-read
        # needed, and it can never legitimately drift between suspend and
        # resume. Reuses the "max_date" key (never parsed as a date by
        # fingerprint_matches, only compared for equality) rather than
        # reshaping the fingerprint dict for this one kind.
        snap = snapshot_store.get_snapshot(spec["snapshot_id"])
        return {
            "row_count": snap.row_count if snap else None,
            "max_date": snap.snapshot_hash if snap else None,
        }
    client = client_for(kind)
    entity, _ = entity_and_field_for_batch(spec, kind, date_field)
    return {
        "row_count": client.count_entity(entity),
        "max_date": _max_date(fetch_date_column(client, entity, date_field)),
    }


def capture_fingerprint(
    *,
    source_kind: str,
    source_spec: dict[str, Any],
    source_date_field: str,
    target_kind: str,
    target_spec: dict[str, Any],
    target_date_field: str,
) -> dict[str, Any]:
    """One row-count + max-business-date pull per side. Called once when a
    suspend is requested (stored on the ``pipeline_run_suspensions`` row) and
    once again at resume time, for :func:`fingerprint_matches` to compare."""
    return {
        "source": _capture_side(source_kind, source_spec, source_date_field),
        "target": _capture_side(target_kind, target_spec, target_date_field),
    }


def fingerprint_matches(old: dict[str, Any], new: dict[str, Any]) -> bool:
    """Exact equality on both sides' row_count/max_date. A ``None`` on either
    side of either capture (the connector couldn't cheaply supply one) never
    silently counts as "unchanged", even if it's ``None`` in both captures —
    an unknown signal always reports "does not match" so the caller degrades
    to asking the user, rather than a false-negative staleness check."""
    for side in ("source", "target"):
        old_side, new_side = old.get(side, {}), new.get(side, {})
        if old_side.get("row_count") is None or new_side.get("row_count") is None:
            return False
        if old_side.get("max_date") is None or new_side.get("max_date") is None:
            return False
        if old_side != new_side:
            return False
    return True
