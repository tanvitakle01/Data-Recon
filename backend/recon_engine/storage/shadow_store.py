"""Shadow_Source store (in-memory) with TTL cleanup.

Shadow sources are derived, disposable datasets. They persist for
``SHADOW_TTL_DAYS`` (default 7) so historical mismatches can be investigated,
then are auto-cleaned. Because every shadow records its
``raw_snapshot_hash`` + ``contract_version``, an expired shadow is fully
reproducible from Raw Snapshot + Contract Version.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import pandas as pd

from backend.recon_engine.config import get_settings
from backend.recon_engine.models.run import ShadowSource
from backend.recon_engine.storage import frames

_SHADOWS: dict[str, ShadowSource] = {}


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
    ttl = settings.shadow_ttl_days if ttl_days is None else ttl_days

    shadow_id = _new_id()
    storage_key = f"shadow:{shadow_id}"
    frames.write_frame(df, storage_key)

    now = datetime.now(timezone.utc)
    shadow = ShadowSource(
        shadow_id=shadow_id,
        run_id=run_id,
        contract_id=contract_id,
        contract_version=contract_version,
        raw_snapshot_id=raw_snapshot_id,
        raw_snapshot_hash=raw_snapshot_hash,
        row_count=int(df.shape[0]),
        storage_path=storage_key,
        created_at=now,
        expires_at=now + timedelta(days=ttl),
    )
    _SHADOWS[shadow_id] = shadow
    return shadow


def get_shadow(shadow_id: str) -> ShadowSource | None:
    return _SHADOWS.get(shadow_id)


def load_shadow_frame(shadow_id: str) -> pd.DataFrame:
    shadow = get_shadow(shadow_id)
    if shadow is None:
        raise KeyError(f"Unknown or expired shadow '{shadow_id}'.")
    return frames.read_frame(shadow.storage_path)


def cleanup_expired(now: datetime | None = None) -> list[str]:
    """Delete shadow sources whose TTL has elapsed. Returns removed shadow ids.

    Removes both the in-memory payload and the metadata record. Idempotent.
    """
    now = now or datetime.now(timezone.utc)
    removed: list[str] = []
    for shadow_id, shadow in list(_SHADOWS.items()):
        if shadow.expires_at <= now:
            frames.delete_frame(shadow.storage_path)
            del _SHADOWS[shadow_id]
            removed.append(shadow_id)
    return removed
