from __future__ import annotations

import traceback
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.excel_comparator.core.auto_mapper import auto_map_columns

router = APIRouter()


class PreviewData(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]


class AutoMapRequest(BaseModel):
    source_preview: PreviewData
    target_preview: PreviewData


@router.post("/api/reconciliation/auto-map")
async def auto_map_endpoint(payload: AutoMapRequest) -> dict[str, Any]:
    try:
        # 1) Convert source/target previews to pandas DataFrames
        source_df = pd.DataFrame(payload.source_preview.rows, columns=payload.source_preview.columns)
        target_df = pd.DataFrame(payload.target_preview.rows, columns=payload.target_preview.columns)

        # Defensive reindex to preserve column order
        if payload.source_preview.columns:
            source_df = source_df.reindex(columns=payload.source_preview.columns)
        if payload.target_preview.columns:
            target_df = target_df.reindex(columns=payload.target_preview.columns)

        # 2) Call existing core auto-mapper logic
        result = auto_map_columns(source_df, target_df)

        # 3) Return mapping + display for read-only UI rendering
        return {
            "success": True,
            "mapping": result["mapping"],
            "display": result["display"],
        }

    except HTTPException:
        raise
    except Exception as exc:
        tb = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Auto-map failed: {exc}\n{tb}")

