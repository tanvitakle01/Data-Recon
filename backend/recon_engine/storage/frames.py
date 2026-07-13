"""DataFrame serialization + content hashing for the persistence layer.

Frames are stored as JSON (columns + row arrays, nulls normalised to ``null``).
This is portable, human-inspectable, and dtype-stable across read/write — the
deterministic operations re-cast types anyway, so exact dtype round-tripping is
not required, but *value* stability (for hashing/reproducibility) is.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


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


def write_frame(df: pd.DataFrame, path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(_to_payload(df), fh, ensure_ascii=False)


def read_frame(path: Path | str) -> pd.DataFrame:
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return pd.DataFrame(payload["data"], columns=payload["columns"])
