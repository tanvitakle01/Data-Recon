"""Shadow_Source store (``recon_shadow`` schema) with TTL cleanup.

Shadow sources are derived, disposable datasets. They persist for
``SHADOW_TTL_DAYS`` (default 7) so historical mismatches can be investigated,
then are auto-cleaned. Because every shadow records its
``raw_snapshot_hash`` + ``contract_version``, an expired shadow is fully
reproducible from Raw Snapshot + Contract Version.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid

import pandas as pd

from backend.recon_engine.config import get_settings
from backend.recon_engine.models.run import ShadowSource
from backend.recon_engine.storage import frames
from backend.recon_engine.storage.db import shadow_db


def _new_id() -> str:
    return "shadow_" + uuid.uuid4().hex


def create_shadow(
    df: pd.DataFrame,
    *,
    run_id: str,
    contract_id: str,
    contract_version: int,
    raw_snapshot_id: str,
    raw_snapshot_hash: str,
    ttl_days: int | None = None,
) -> ShadowSource:
    settings = get_settings()
    settings.ensure_dirs()
    ttl = settings.shadow_ttl_days if ttl_days is None else ttl_days

    shadow_id = _new_id()
    storage_path = str(settings.shadow_data_dir / f"{shadow_id}.json")
    frames.write_frame(df, storage_path)

    now = datetime.now(timezone.utc)
    shadow = ShadowSource(
        shadow_id=shadow_id,
        run_id=run_id,
        contract_id=contract_id,
        contract_version=contract_version,
        raw_snapshot_id=raw_snapshot_id,
        raw_snapshot_hash=raw_snapshot_hash,
        row_count=int(df.shape[0]),
        storage_path=storage_path,
        created_at=now,
        expires_at=now + timedelta(days=ttl),
    )

    with shadow_db() as conn:
        conn.execute(
            """INSERT INTO shadow_sources
               (shadow_id, run_id, contract_id, contract_version, raw_snapshot_id,
                raw_snapshot_hash, row_count, storage_path, created_at, expires_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                shadow.shadow_id, shadow.run_id, shadow.contract_id, shadow.contract_version,
                shadow.raw_snapshot_id, shadow.raw_snapshot_hash, shadow.row_count,
                shadow.storage_path, shadow.created_at.isoformat(), shadow.expires_at.isoformat(),
            ),
        )
    return shadow


def _row_to_shadow(row) -> ShadowSource:
    return ShadowSource(
        shadow_id=row["shadow_id"],
        run_id=row["run_id"],
        contract_id=row["contract_id"],
        contract_version=row["contract_version"],
        raw_snapshot_id=row["raw_snapshot_id"],
        raw_snapshot_hash=row["raw_snapshot_hash"],
        row_count=row["row_count"],
        storage_path=row["storage_path"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )


def get_shadow(shadow_id: str) -> ShadowSource | None:
    with shadow_db() as conn:
        row = conn.execute(
            "SELECT * FROM shadow_sources WHERE shadow_id = ?", (shadow_id,)
        ).fetchone()
    return _row_to_shadow(row) if row else None


def load_shadow_frame(shadow_id: str) -> pd.DataFrame:
    shadow = get_shadow(shadow_id)
    if shadow is None:
        raise KeyError(f"Unknown or expired shadow '{shadow_id}'.")
    return frames.read_frame(shadow.storage_path)


def cleanup_expired(now: datetime | None = None) -> list[str]:
    """Delete shadow sources whose TTL has elapsed. Returns removed shadow ids.

    Removes both the on-disk payload and the metadata row. Idempotent.
    """
    now = now or datetime.now(timezone.utc)
    with shadow_db() as conn:
        rows = conn.execute(
            "SELECT shadow_id, storage_path FROM shadow_sources WHERE expires_at <= ?",
            (now.isoformat(),),
        ).fetchall()
        removed: list[str] = []
        for row in rows:
            Path(row["storage_path"]).unlink(missing_ok=True)
            conn.execute("DELETE FROM shadow_sources WHERE shadow_id = ?", (row["shadow_id"],))
            removed.append(row["shadow_id"])
    return removed
