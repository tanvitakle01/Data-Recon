"""In-memory store for chat-uploaded file bytes, keyed by an opaque id.

Mirrors ``backend/routes/reconcile.py``'s ``_FILE_STORE`` pattern (this repo
has no persisted file service yet). Lets the frontend carry a small
``{"filename": ..., "file_id": ...}`` in its chat state across turns instead
of re-uploading the same file's bytes on every message — the file is only
needed once (read here when a role is actually acted on), and again if a
later turn adds the missing piece of a multi-file request.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

_STORE: dict[str, dict[str, Any]] = {}


def save(filename: str, content: bytes) -> str:
    file_id = uuid4().hex
    _STORE[file_id] = {"filename": filename, "content": content}
    return file_id


def load(file_id: str) -> tuple[str, bytes]:
    entry = _STORE.get(file_id)
    if entry is None:
        raise KeyError(f"Unknown chat attachment '{file_id}' (may have expired).")
    return entry["filename"], entry["content"]
