from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

import pandas as pd
from fastapi import APIRouter, File, UploadFile, HTTPException, Body

from backend.ai.insight_engine import InsightEngine
from backend.excel_comparator.core.loader import load_excel

logger = logging.getLogger(__name__)

router = APIRouter()

# Reuse the same in-memory store used by backend/routes/reconcile.py
try:
    from backend.routes.reconcile import _FILE_STORE  # type: ignore
except Exception:  # pragma: no cover
    _FILE_STORE: dict[str, dict[str, Any]] = {}


def _load_df_from_upload(upload: UploadFile, sheet_name: str | None = None) -> dict[str, Any]:
    filename_l = (upload.filename or "").lower()
    if not (filename_l.endswith(".xlsx") or filename_l.endswith(".xls")):
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload .xlsx or .xls")

    try:
        content = upload.file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        loaded = load_excel(BytesIO(content), sheet_name=sheet_name)
        # Ensure we keep sheet->df contract from existing loader usage.
        loaded["name"] = upload.filename
        loaded["bytes"] = content
        return loaded
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Bad Excel file: {exc}")


@router.post("/insights/from-file-id")
async def generate_insights_from_file_id(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """
    Generates insights from an already-generated reconciliation dataset stored in-memory.
    Expects: { "file_id": "<id from /reconcile response>" }
    """
    file_id = body.get("file_id")
    if not file_id:
        raise HTTPException(status_code=400, detail="Missing file_id")

    entry = _FILE_STORE.get(str(file_id))
    if not entry:
        raise HTTPException(status_code=404, detail="Reconciliation file_id not found")

    file_bytes = entry.get("bytes")
    if not isinstance(file_bytes, (bytes, bytearray)):
        raise HTTPException(status_code=404, detail="Stored dataset bytes not found for this file_id")

    try:
        # Insights engine relies on the dataframe shape (incl. "Remarks" column).
        loaded = load_excel(BytesIO(file_bytes))
        df: pd.DataFrame = loaded["df"]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to load stored reconciliation output: {exc}")

    if df is None or df.empty:
        return InsightEngine().generate(pd.DataFrame())

    payload = InsightEngine().generate(df)
    return {"success": True, "payload": payload}


@router.post("/insights")
async def generate_insights(
    file: UploadFile = File(..., description="Compared/output Excel file containing 'Remarks' column"),
    sheet_name: str = "",
) -> dict[str, Any]:
    """
    Generates dashboard-ready mismatch insights.
    This route is intentionally separate from /api/reconcile.
    """
    sheet = str(sheet_name).strip() or None

    loaded = _load_df_from_upload(file, sheet)
    df: pd.DataFrame = loaded["df"]

    if df is None or df.empty:
        return InsightEngine().generate(pd.DataFrame())

    payload = InsightEngine().generate(df)
    return {
        "success": True,
        "payload": payload,
    }
