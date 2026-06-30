from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

# Import the same in-memory store used by backend/routes/reconcile.py.
# This keeps the implementation minimal and avoids changing existing architecture.
try:
    from backend.routes.reconcile import _FILE_STORE  # type: ignore
except Exception:  # pragma: no cover
    _FILE_STORE: dict[str, dict[str, Any]] = {}

router = APIRouter(prefix="/api/files")


@router.get("/download/{file_id}")
async def download_file(file_id: str):
    if file_id not in _FILE_STORE:
        raise HTTPException(status_code=404, detail="File not found")

    entry = _FILE_STORE[file_id]
    if not entry.get("generated"):
        raise HTTPException(status_code=404, detail="File not generated")

    file_bytes = entry.get("bytes")
    filename = entry.get("filename") or f"download_{file_id}.xlsx"

    if not isinstance(file_bytes, (bytes, bytearray)):
        raise HTTPException(status_code=500, detail="Stored file content invalid")

    async def _iter():
        yield bytes(file_bytes)

    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return StreamingResponse(_iter(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)

