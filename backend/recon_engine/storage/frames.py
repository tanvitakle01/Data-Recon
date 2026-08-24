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


def append_frame(df: pd.DataFrame, path: Path | str) -> None:
    """Appends ``df``'s rows to a JSON-Lines file at ``path`` — a header line
    (``{"columns": [...]}``) written once, then one ``{"row": [...]}`` line
    per row. Used by the streaming batch orchestrator
    (``result_store.append_batch_result``) so appending a batch's detail rows
    is O(batch), not O(everything-written-so-far) the way a read-modify-write
    over :func:`write_frame`'s single-blob format would be.

    A distinct on-disk format from :func:`write_frame`/:func:`read_frame` —
    read back with :func:`read_frame_jsonl`, never :func:`read_frame`. Every
    append must carry the SAME columns (one contract's reconciliation detail
    shape never changes batch to batch); a mismatch is a caller bug, not
    handled here.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _to_payload(df)
    write_header = not path.exists()
    with path.open("a", encoding="utf-8") as fh:
        if write_header:
            fh.write(json.dumps({"columns": payload["columns"]}, ensure_ascii=False) + "\n")
        for row in payload["data"]:
            fh.write(json.dumps({"row": row}, ensure_ascii=False) + "\n")


def read_frame_jsonl(path: Path | str) -> pd.DataFrame:
    """Reads back every row appended via :func:`append_frame`. Returns an
    empty DataFrame if the file doesn't exist yet (a run that hasn't
    completed its first batch)."""
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    columns: list[str] | None = None
    rows: list[list[Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if "columns" in record:
                columns = record["columns"]
            else:
                rows.append(record["row"])
    if columns is None:
        return pd.DataFrame()
    return pd.DataFrame(rows, columns=columns)
