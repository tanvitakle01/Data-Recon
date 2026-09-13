"""In-memory DataFrame storage + content hashing for the persistence layer.

Frames are held as plain ``pandas.DataFrame`` objects in process memory, keyed
by an opaque string handle the caller controls (historically a filesystem
path — the name is kept for API compatibility, but nothing here touches disk).
This is Stage-1's stateless design: everything lives only as long as the
process runs, and a restart loses it — that's correct behavior, not a bug.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pandas as pd

_FRAME_STORE: dict[str, pd.DataFrame] = {}


def _to_payload(df: pd.DataFrame) -> dict[str, Any]:
    normalised = df.astype(object).where(pd.notna(df), None)
    return {
        "columns": [str(c) for c in df.columns],
        "data": normalised.values.tolist(),
    }


def compute_frame_hash(df: pd.DataFrame) -> str:
    """Deterministic SHA-256 of a frame's columns + values.

    Values are stringified so the hash is stable regardless of numpy dtype
    quirks. Same data + same column order == same hash == reproducible.
    """
    payload = _to_payload(df)
    canonical = {
        "columns": payload["columns"],
        "data": [[None if v is None else str(v) for v in row] for row in payload["data"]],
    }
    blob = json.dumps(canonical, sort_keys=False, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def write_frame(df: pd.DataFrame, key: str) -> None:
    _FRAME_STORE[str(key)] = df.copy()


def read_frame(key: str) -> pd.DataFrame:
    key = str(key)
    if key.endswith(".jsonl"):
        # Mirrors the on-disk implementation this replaces: a single-blob
        # reader can't parse a streaming/JSONL-accumulated frame — callers
        # must use read_frame_jsonl for those.
        raise ValueError(f"{key!r} holds a streaming frame; use read_frame_jsonl instead.")
    if key not in _FRAME_STORE:
        raise FileNotFoundError(f"No frame stored under {key!r}.")
    return _FRAME_STORE[key].copy()


def append_frame(df: pd.DataFrame, key: str) -> None:
    """Appends ``df``'s rows onto whatever is already stored under ``key``.

    A no-op on a 0-row frame, matching the on-disk implementation this
    replaces — a batch whose window matched nothing must never define (or
    overwrite) the accumulated columns for this key.
    """
    if df.empty:
        return
    key = str(key)
    existing = _FRAME_STORE.get(key)
    if existing is None:
        _FRAME_STORE[key] = df.reset_index(drop=True)
    else:
        _FRAME_STORE[key] = pd.concat([existing, df], ignore_index=True)


def read_frame_jsonl(key: str) -> pd.DataFrame:
    """Reads back every row accumulated via :func:`append_frame`. Returns an
    empty DataFrame if nothing has been appended yet (a run that hasn't
    completed its first batch)."""
    return _FRAME_STORE.get(str(key), pd.DataFrame()).copy()


def delete_frame(key: str) -> None:
    _FRAME_STORE.pop(str(key), None)
