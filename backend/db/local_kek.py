"""Local-dev replacement for :mod:`backend.db.vault`.

Supabase Vault isn't reachable without a real network path to
``*.supabase.co``, so for local dev the KEK instead lives in a single local
file, generated on first use. Same ``get_kek`` signature as the Vault
version, so :mod:`backend.crypto.envelope` and
:mod:`backend.connections.store` don't need to know which backend they're
talking to.

Not a secret-management story for anything beyond a developer's own machine
— the file this writes to (``backend/.local_kek`` by default) must stay out
of version control.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from backend.settings import get_app_settings

_KEK_LEN = 32


def get_kek(key_id: str | None = None) -> bytes:
    """Return the local KEK as raw bytes, generating and persisting one on
    first use. ``key_id`` is accepted for signature compatibility with the
    Vault version but is otherwise unused — there's only ever one local KEK.
    """
    settings = get_app_settings()
    path = Path(settings.local_kek_path)

    if path.is_file():
        return base64.b64decode(path.read_text(encoding="utf-8").strip())

    kek = os.urandom(_KEK_LEN)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(base64.b64encode(kek).decode("ascii"), encoding="utf-8")
    return kek
