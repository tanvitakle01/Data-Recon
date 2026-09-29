from __future__ import annotations

import json
from urllib.parse import quote
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from backend.excel_comparator.core.multi_file_join import (
    JoinConfigError,
    JoinSort,
    JoinStep,
    join_files,
    summary,
    to_bytes,
)

# Parsing-layer only: joins several uploaded files into one combined file for a
# single wizard slot. It never touches snapshots, contracts or reconciliation —
# the wizard uploads the returned file downstream exactly as if the user had
# uploaded it themselves.
router = APIRouter(prefix="/api/files")

_MAX_PREVIEW_ROWS = 50


def _parse_config(raw: str) -> tuple[list[str | None], list[JoinStep], JoinSort | None]:
    try:
        cfg: dict[str, Any] = json.loads(raw or "{}")
        steps = [
            JoinStep(
                left_file=int(s["left_file"]),
                left_column=str(s["left_column"]),
                right_column=str(s["right_column"]),
                how=str(s.get("how") or "left"),
            )
            for s in cfg.get("steps") or []
        ]
        sort_cfg = cfg.get("sort")
        sort = JoinSort(step=int(sort_cfg["step"]), direction=str(sort_cfg["direction"])) if sort_cfg else None
        sheets = [s or None for s in cfg.get("sheets") or []]
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid join configuration: {exc}") from exc
    return sheets, steps, sort


def _content_disposition(filename: str) -> str:
    # Headers are Latin-1 only: ASCII fallback plus the RFC 5987 UTF-8 form.
    fallback = filename.encode("ascii", "replace").decode("ascii").replace("?", "_").replace('"', "_")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


@router.post("/join")
async def join_uploaded_files(
    files: list[UploadFile] = File(...),
    config: str = Form(...),
    mode: str = Form(default="preview"),
    preview_rows: int = Form(default=10),
):
    """``mode=preview`` → JSON stats + combined preview; ``mode=build`` → the
    combined file itself (CSV for CSV inputs, .xlsx for Excel inputs)."""
    sheets, steps, sort = _parse_config(config)
    payload = [(f.filename or "", await f.read()) for f in files]
    rows = max(1, min(int(preview_rows), _MAX_PREVIEW_ROWS))

    try:
        result = join_files(payload, sheets, steps, sort, preview_rows=rows)
    except JoinConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if mode == "build":
        body, media_type = to_bytes(result)
        return Response(
            content=body,
            media_type=media_type,
            headers={"Content-Disposition": _content_disposition(result.filename)},
        )
    return summary(result, preview_rows=rows)
