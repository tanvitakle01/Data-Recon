"""KEK retrieval from Supabase Vault.

`vault.decrypted_secrets` is service_role-only by Supabase's own design, so
this module is the sole caller of :func:`backend.db.postgres.admin_connection`
for KEK reads. The KEK is cached in-process for a few minutes — long enough
to avoid a Vault round trip on every request, short enough that a rotation
(inserting a new Vault secret + a new `kek_key_id` on new connections) is
picked up without restarting every backend process.
"""

from __future__ import annotations

import base64
import time

from backend.db.postgres import admin_connection
from backend.settings import get_app_settings

_CACHE_TTL_SECONDS = 300
_cache: dict[str, tuple[bytes, float]] = {}


def get_kek(key_id: str | None = None) -> bytes:
    """Return the current KEK as raw bytes, decoded from its base64 form in Vault."""
    settings = get_app_settings()
    name = key_id or settings.kek_vault_secret_name

    cached = _cache.get(name)
    now = time.monotonic()
    if cached is not None and now - cached[1] < _CACHE_TTL_SECONDS:
        return cached[0]

    with admin_connection() as conn:
        row = conn.execute(
            "select decrypted_secret from vault.decrypted_secrets where name = %s",
            (name,),
        ).fetchone()
    if row is None:
        raise RuntimeError(f"Vault secret '{name}' not found — has it been created?")

    kek = base64.b64decode(row[0])
    _cache[name] = (kek, now)
    return kek


def reset_kek_cache() -> None:
    _cache.clear()
