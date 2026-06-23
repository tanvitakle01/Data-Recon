from __future__ import annotations

from io import BytesIO
from typing import Any

from fastapi import APIRouter, File, UploadFile, HTTPException, Form

import pandas as pd

from backend.excel_comparator.core.auto_mapper import auto_map_columns
from backend.excel_comparator.core.loader import load_excel

router = APIRouter()


@router.post("/automap")
async def automap_route(
    source_file: UploadFile = File(...),
    target_file: UploadFile = File(...),
    sheet_name_source: str | None = Form(default=None),
    sheet_name_target: str | None = Form(default=None),
) -> dict[str, Any]:
    """Return the auto-mapping result unchanged.

    Mirrors the Streamlit workflow:
      mapping_result = auto_map_columns(source_df, target_df)

    Returns:
      {
        "display": [...],
        "mapping": {...}
      }
    """

    try:
        source_content = await source_file.read()
        target_content = await target_file.read()

        source_loaded = load_excel(BytesIO(source_content), sheet_name=sheet_name_source)
        target_loaded = load_excel(BytesIO(target_content), sheet_name=sheet_name_target)

        source_df: pd.DataFrame = source_loaded["df"]
        target_df: pd.DataFrame = target_loaded["df"]

        return auto_map_columns(source_df, target_df)

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Auto-mapping failed: {exc}")

