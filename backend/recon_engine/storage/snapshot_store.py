"""Immutable, append-only raw snapshot store (in-memory).

By design this module exposes NO update or delete operation. Once written, a
snapshot's metadata record and payload frame are never mutated — satisfying
the "raw data immutable / never overwrite snapshots" requirement structurally.
Held only in process memory — a restart loses every snapshot, which is
correct for a stateless, single-session deployment.
"""

from __future__ import annotations

import uuid

import pandas as pd

from backend.recon_engine.models.snapshot import RawLayer, RawSnapshot
from backend.recon_engine.storage import frames

_SNAPSHOTS: dict[str, RawSnapshot] = {}


def _new_id() -> str:
    return "snap_" + uuid.uuid4().hex


def create_snapshot(
    df: pd.DataFrame,
    *,
    layer: RawLayer,
    source_type: str,
    comparison_type: str | None = None,
    created_by: str = "system",
    lineage: dict | None = None,
) -> RawSnapshot:
    """Persist a new immutable snapshot and return its metadata record."""
    snapshot_id = _new_id()
    storage_key = f"snapshot:{snapshot_id}"
    frames.write_frame(df, storage_key)

    snap = RawSnapshot(
        snapshot_id=snapshot_id,
        layer=layer,
        source_type=source_type,
        comparison_type=comparison_type,
        snapshot_hash=frames.compute_frame_hash(df),
        row_count=int(df.shape[0]),
        columns=[str(c) for c in df.columns],
        created_by=created_by,
        storage_path=storage_key,
        lineage=lineage or {},
    )
    _SNAPSHOTS[snapshot_id] = snap
    return snap


def get_snapshot(snapshot_id: str) -> RawSnapshot | None:
    return _SNAPSHOTS.get(snapshot_id)


def load_snapshot_frame(snapshot_id: str) -> pd.DataFrame:
    snap = get_snapshot(snapshot_id)
    if snap is None:
        raise KeyError(f"Unknown snapshot '{snapshot_id}'.")
    return frames.read_frame(snap.storage_path)


def list_snapshots(layer: RawLayer | None = None) -> list[RawSnapshot]:
    values = sorted(_SNAPSHOTS.values(), key=lambda s: s.created_at, reverse=True)
    if layer is not None:
        values = [s for s in values if s.layer == layer]
    return values
