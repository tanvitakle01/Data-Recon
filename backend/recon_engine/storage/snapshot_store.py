"""Immutable, append-only raw snapshot store.

By design this module exposes NO update or delete operation. Once written, a
snapshot's metadata row and payload file are never mutated — satisfying the
"raw data immutable / never overwrite snapshots" requirement structurally.
"""

from __future__ import annotations

import json
import uuid

import pandas as pd

from backend.recon_engine.config import get_settings
from backend.recon_engine.models.snapshot import RawLayer, RawSnapshot
from backend.recon_engine.storage import frames
from backend.recon_engine.storage.db import main_db


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
    settings = get_settings()
    settings.ensure_dirs()

    snapshot_id = _new_id()
    storage_path = str(settings.raw_data_dir / f"{snapshot_id}.json")
    frames.write_frame(df, storage_path)

    snap = RawSnapshot(
        snapshot_id=snapshot_id,
        layer=layer,
        source_type=source_type,
        comparison_type=comparison_type,
        snapshot_hash=frames.compute_frame_hash(df),
        row_count=int(df.shape[0]),
        columns=[str(c) for c in df.columns],
        created_by=created_by,
        storage_path=storage_path,
        lineage=lineage or {},
    )

    with main_db() as conn:
        conn.execute(
            """INSERT INTO raw_snapshots
               (snapshot_id, layer, source_type, comparison_type, snapshot_hash,
                row_count, columns_json, created_at, created_by, storage_path, lineage_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                snap.snapshot_id, snap.layer.value, snap.source_type, snap.comparison_type,
                snap.snapshot_hash, snap.row_count, json.dumps(snap.columns),
                snap.created_at.isoformat(), snap.created_by, snap.storage_path,
                json.dumps(snap.lineage),
            ),
        )
    return snap


def _row_to_snapshot(row) -> RawSnapshot:
    return RawSnapshot(
        snapshot_id=row["snapshot_id"],
        layer=RawLayer(row["layer"]),
        source_type=row["source_type"],
        comparison_type=row["comparison_type"],
        snapshot_hash=row["snapshot_hash"],
        row_count=row["row_count"],
        columns=json.loads(row["columns_json"]),
        created_at=row["created_at"],
        created_by=row["created_by"],
        storage_path=row["storage_path"],
        lineage=json.loads(row["lineage_json"]),
    )


def get_snapshot(snapshot_id: str) -> RawSnapshot | None:
    with main_db() as conn:
        row = conn.execute(
            "SELECT * FROM raw_snapshots WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchone()
    return _row_to_snapshot(row) if row else None


def load_snapshot_frame(snapshot_id: str) -> pd.DataFrame:
    snap = get_snapshot(snapshot_id)
    if snap is None:
        raise KeyError(f"Unknown snapshot '{snapshot_id}'.")
    return frames.read_frame(snap.storage_path)


def list_snapshots(layer: RawLayer | None = None) -> list[RawSnapshot]:
    with main_db() as conn:
        if layer is None:
            rows = conn.execute(
                "SELECT * FROM raw_snapshots ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM raw_snapshots WHERE layer = ? ORDER BY created_at DESC",
                (layer.value,),
            ).fetchall()
    return [_row_to_snapshot(r) for r in rows]
