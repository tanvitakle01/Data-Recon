from __future__ import annotations

from typing import Any, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from starlette.datastructures import UploadFile

from backend.excel_comparator.core.auto_mapper import auto_map_columns
from backend.excel_comparator.core.date_alignment import build_alignment

# Reuse the manual-form helpers + loaders from the reconcile route so the two
# endpoints resolve source/target sides identically (files or JSON rows).
from backend.routes.reconcile import (
    _MAX_PART_SIZE,
    _form_optional_str,
    _form_str,
    _form_upload,
    _load_excel_from_upload,
    _load_rows_from_json,
)

router = APIRouter()


def _resolve_df(
    rows_json: Optional[str],
    upload: Optional[UploadFile],
    sheet: str | None,
    label: str,
) -> pd.DataFrame:
    if rows_json is not None:
        return _load_rows_from_json(rows_json, f"{label}_rows")
    if upload is not None:
        return _load_excel_from_upload(upload, sheet)["df"]
    raise HTTPException(
        status_code=400,
        detail=f"Missing {label} data: provide {label}_file or {label}_rows.",
    )


@router.post("/automap")
async def automap_route(request: Request) -> dict[str, Any]:
    """Return the auto-mapping result unchanged.

    Accepts either uploaded Excel files (`source_file`/`target_file`) or
    already-fetched JSON rows (`source_rows`/`target_rows`), matching the
    input modes of /reconcile, so auto-mapping works for SAP-fetched data
    and Excel uploads alike.

    Returns:
      {
        "display": [...],
        "mapping": {...},
        "date_alignment": {...}
      }
    """
    form = await request.form(max_part_size=_MAX_PART_SIZE)

    source_file = _form_upload(form, "source_file")
    target_file = _form_upload(form, "target_file")
    source_rows = _form_optional_str(form, "source_rows")
    target_rows = _form_optional_str(form, "target_rows")
    src_sheet = (_form_str(form, "sheet_name_source") or "").strip() or None
    tgt_sheet = (_form_str(form, "sheet_name_target") or "").strip() or None

    try:
        source_df = _resolve_df(source_rows, source_file, src_sheet, "source")
        target_df = _resolve_df(target_rows, target_file, tgt_sheet, "target")

        result = auto_map_columns(source_df, target_df)
        result["date_alignment"] = build_alignment(source_df, target_df)
        return result

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Auto-mapping failed: {exc}")
