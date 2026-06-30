from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from binascii import hexlify
from io import BytesIO
from typing import Any, Optional
from uuid import uuid4

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.excel_comparator.core.comparator import ExcelComparator
from backend.excel_comparator.core.loader import load_excel
from backend.excel_comparator.core.mapper import ColumnMapper
from backend.excel_comparator.core.writer import write_annotated_excel
from backend.excel_comparator.utils.helpers import get_output_filename

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory output bytes store.
# This repo does not have a persisted file service yet.
_FILE_STORE: dict[str, dict[str, Any]] = {}


def _compute_summary_from_remarks(remarks_df: pd.DataFrame) -> dict[str, int]:
    """Frontend requires these exact counters derived from the Remarks markers."""
    if remarks_df is None or remarks_df.empty or "Remarks" not in remarks_df.columns:
        return {
            "matched": 0,
            "qty_mismatch": 0,
            "missing_in_target": 0,
            "extra_in_target": 0,
        }

    remarks = remarks_df["Remarks"].fillna("").astype(str)
    return {
        "matched": int(remarks.str.startswith("✅").sum()),
        "qty_mismatch": int(remarks.str.startswith("⚠️").sum()),
        "missing_in_target": int(remarks.str.startswith("❌").sum()),
        "extra_in_target": int(remarks.str.startswith("🔶").sum()),
    }


def _parse_scenarios(scenarios_raw: Optional[str]) -> list[int]:
    if scenarios_raw is None:
        return [1, 2, 3, 4]

    s = str(scenarios_raw).strip()
    if not s:
        return [1, 2, 3, 4]

    # Accept: "[1,2,3]" or "1,2,3" or "1"
    try:
        if s.startswith("[") and s.endswith("]"):
            items = json.loads(s)
        else:
            # comma-separated
            items = [x.strip() for x in s.split(",") if x.strip()]

        scenarios: list[int] = [int(x) for x in items]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid scenarios: {exc}")

    allowed = {1, 2, 3, 4}
    invalid = [x for x in scenarios if x not in allowed]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid scenario(s): {invalid}. Allowed: 1,2,3,4")

    # de-dup while preserving order
    seen: set[int] = set()
    out: list[int] = []
    for x in scenarios:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


def _parse_mapping(mapping_json: Optional[str]) -> dict[str, Any]:
    if not mapping_json:
        raise HTTPException(status_code=400, detail="Missing mapping_json")

    try:
        mapping = json.loads(mapping_json)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid mapping_json: {exc}")

    if not isinstance(mapping, dict):
        raise HTTPException(status_code=400, detail="Invalid mapping_json: expected an object")

    return mapping


def _load_excel_from_upload(upload: UploadFile, sheet_name: str | None) -> dict[str, Any]:
    # Validate file extension early.
    filename_l = (upload.filename or "").lower()
    if not (filename_l.endswith(".xlsx") or filename_l.endswith(".xls")):
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload .xlsx or .xls")

    try:
        content = upload.file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        loaded = load_excel(BytesIO(content), sheet_name=sheet_name)
        loaded["name"] = upload.filename
        loaded["bytes"] = content
        return loaded
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Bad Excel file: {exc}")


def _build_download_url(file_id: str) -> str:
    # Contract requested: /api/files/download/{file_id}
    return f"/api/files/download/{file_id}"


@dataclass(frozen=True)
class _ResponseFile:
    filename: str
    download_url: str


@router.post("/reconcile")
async def reconcile(
    source_file: UploadFile = File(...),
    target_file: UploadFile = File(...),
    sheet_name_source: str = Form(default=""),
    sheet_name_target: str = Form(default=""),
    mapping_json: Optional[str] = Form(default=None),
    # allow frontend to send mapping as `mapping` (if it ever does)
    mapping: Optional[str] = Form(default=None),
    scenarios: Optional[str] = Form(default=None),
    scenario_list: Optional[str] = Form(default=None),
) -> dict[str, Any]:

    """Single endpoint that performs mapping validation + reconciliation.

    Multipart request contract is used to match the existing frontend.
    """

    # Parse optional sheet names.
    src_sheet = str(sheet_name_source).strip() or None
    tgt_sheet = str(sheet_name_target).strip() or None

    # Parse mapping and scenarios.
    # Prefer mapping_json; allow fallback to `mapping` (legacy/alternative field name).
    raw_mapping = mapping_json or mapping
    mapping = _parse_mapping(raw_mapping)

    # TEMP DEBUG: validate mapping parsed shape (do NOT log file contents)
    try:
        kf = mapping.get("key_fields", [])
        cf = mapping.get("compare_fields", [])
        logger.info(
            "Received mapping_json parsed keys: %s; key_fields=%s compare_fields=%s",
            list(mapping.keys()),
            len(kf) if isinstance(kf, list) else "?",
            len(cf) if isinstance(cf, list) else "?",
        )
    except Exception:
        logger.info("Received mapping_json but failed to compute field counts")


    # scenarios can arrive as `scenarios` or `scenario_list`
    raw_scenarios = scenarios if scenarios is not None else scenario_list
    scenarios_list = _parse_scenarios(raw_scenarios)


    # Load Excel -> DataFrames + keep original target bytes for writer formatting.
    source_loaded = _load_excel_from_upload(source_file, src_sheet)
    target_loaded = _load_excel_from_upload(target_file, tgt_sheet)

    source_df: pd.DataFrame = source_loaded["df"]
    target_df: pd.DataFrame = target_loaded["df"]

    # Validate + reconcile (core logic orchestrated only).
    mapper = ColumnMapper(mapping)
    mapper.validate(source_df, target_df)

    comparator = ExcelComparator(source_df, target_df, mapper)
    result_df, _summary = comparator.run(scenarios_list)

    # Clean helper columns if any.
    helper_cols = [c for c in result_df.columns if c.startswith("__")]
    if helper_cols:
        result_df = result_df.drop(columns=helper_cols, errors="ignore")

    # Build summary strictly from Remarks markers.
    summary = _compute_summary_from_remarks(result_df)

    # Generate output Excel.
    original_target_bytes: bytes = target_loaded["bytes"]
    output_sheet_name = "Compared_Output"

    output_bytes_io = write_annotated_excel(
        result_df,
        original_target_path=BytesIO(original_target_bytes),
        sheet_name=output_sheet_name,
    )

    file_id = uuid4().hex
    filename = get_output_filename(str(target_loaded.get("name") or "target.xlsx"))

    _FILE_STORE[file_id] = {
        "filename": filename,
        "bytes": output_bytes_io.getvalue(),
        "generated": True,
    }

    response_file = _ResponseFile(filename=filename, download_url=_build_download_url(file_id))

    # Return preview only.
    preview_df = result_df.head(200)
    preview_rows = preview_df.astype(object).where(pd.notna(preview_df), None).to_dict(orient="records")

    return {
        "success": True,
        "file_id": file_id,
        "summary": summary,
        "file": {
            "filename": response_file.filename,
            "download_url": response_file.download_url,
        },
        "preview_rows": preview_rows,
    }

