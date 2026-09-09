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
from fastapi import APIRouter, HTTPException, Request
# NOTE: request.form() is parsed by Starlette and yields
# starlette.datastructures.UploadFile instances. fastapi.UploadFile is a
# *subclass* of that, so isinstance(value, fastapi.UploadFile) is False for
# manually-parsed form files — which silently dropped every Excel upload
# ("Missing source_file/target_file"). Check against the Starlette base class.
from starlette.datastructures import UploadFile

from backend.excel_comparator.core.auto_mapper import auto_map_columns
from backend.excel_comparator.core.comparator import ExcelComparator
from backend.excel_comparator.core.date_alignment import build_alignment, filter_to_window
from backend.excel_comparator.core.loader import load_tabular_detailed
from backend.excel_comparator.core.mapper import ColumnMapper
from backend.excel_comparator.core.writer import write_annotated_excel
from backend.excel_comparator.utils.helpers import get_output_filename

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory output bytes store.
# This repo does not have a persisted file service yet.
_FILE_STORE: dict[str, dict[str, Any]] = {}

# SAP-fetch mode sends thousands of rows as a single JSON-string form field
# (source_rows/target_rows). FastAPI's default Form() parsing caps a single
# multipart part at 1MB, which real S/4 (~150KB) and especially IBP
# (1MB+ for 10k+ rows) payloads can exceed — so this route parses the form
# manually with a much higher per-part limit instead of using Form()/File().
_MAX_PART_SIZE = 64 * 1024 * 1024  # 64MB per field


def _form_str(form, key: str, default: str = "") -> str:
    value = form.get(key)
    if value is None or isinstance(value, UploadFile):
        return default
    return str(value)


def _form_optional_str(form, key: str) -> Optional[str]:
    value = form.get(key)
    if value is None or isinstance(value, UploadFile):
        return None
    return str(value)


def _form_upload(form, key: str) -> Optional[UploadFile]:
    value = form.get(key)
    return value if isinstance(value, UploadFile) else None


def _form_bool(form, key: str, default: bool = False) -> bool:
    value = _form_optional_str(form, key)
    if value is None:
        return default
    return value.strip().lower() in {"true", "1", "yes", "on"}


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
    if not (filename_l.endswith(".xlsx") or filename_l.endswith(".xls") or filename_l.endswith(".csv")):
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload .xlsx, .xls, or .csv")

    try:
        content = upload.file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        loaded = load_tabular_detailed(content, upload.filename or "", sheet_name=sheet_name)
        loaded["name"] = upload.filename
        loaded["bytes"] = content
        return loaded
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Bad file: {exc}")


def _load_rows_from_json(rows_json: Optional[str], label: str) -> pd.DataFrame:
    try:
        rows = json.loads(rows_json) if rows_json else []
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {label}: {exc}")

    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail=f"Invalid {label}: expected a list of rows")

    if not rows:
        raise HTTPException(
            status_code=400,
            detail=f"No {label} data to reconcile — fetch or upload the dataset first.",
        )

    return pd.DataFrame(rows)


def _resolve_side(
    rows_json: Optional[str],
    upload: Optional[UploadFile],
    sheet: str | None,
    label: str,
) -> tuple[pd.DataFrame, Optional[bytes], Optional[str]]:
    """Resolve one reconciliation side to (DataFrame, original_bytes, name).

    A side is "rows" when its `*_rows` JSON field is present (SAP fetch),
    otherwise an uploaded Excel file. Resolving each side independently means
    any combination works: Excel↔Excel, S/4↔IBP, or mixed. `original_bytes`
    is only populated for Excel uploads (used by the writer to copy column
    widths); it is None for row-based sides.
    """
    if rows_json is not None:
        return _load_rows_from_json(rows_json, f"{label}_rows"), None, None
    if upload is not None:
        loaded = _load_excel_from_upload(upload, sheet)
        return loaded["df"], loaded["bytes"], str(loaded.get("name") or f"{label}.xlsx")
    raise HTTPException(
        status_code=400,
        detail=f"Missing {label} data: provide {label}_file or {label}_rows.",
    )


def _build_download_url(file_id: str) -> str:
    # Contract requested: /api/files/download/{file_id}
    return f"/api/files/download/{file_id}"


@dataclass(frozen=True)
class _ResponseFile:
    filename: str
    download_url: str


@router.post("/reconcile")
async def reconcile(request: Request) -> dict[str, Any]:
    """Single endpoint that performs mapping validation + reconciliation.

    Supports two input modes that both funnel into the same comparison
    pipeline (ColumnMapper + ExcelComparator):
      - Excel upload: `source_file` + `target_file` multipart uploads.
      - SAP fetch: `source_rows` + `target_rows` JSON arrays (S/4 and IBP
        rows already fetched by the frontend).

    Parses the multipart form manually (rather than via Form()/File()
    parameters) so the per-field size cap can be raised — see
    `_MAX_PART_SIZE`.
    """
    form = await request.form(max_part_size=_MAX_PART_SIZE)

    source_file = _form_upload(form, "source_file")
    target_file = _form_upload(form, "target_file")
    sheet_name_source = _form_str(form, "sheet_name_source")
    sheet_name_target = _form_str(form, "sheet_name_target")
    mapping_json = _form_optional_str(form, "mapping_json")
    # allow frontend to send mapping as `mapping` (if it ever does)
    mapping = _form_optional_str(form, "mapping")
    scenarios = _form_optional_str(form, "scenarios")
    scenario_list = _form_optional_str(form, "scenario_list")
    # SAP-fetch mode: rows already fetched from S/4 and IBP, sent as JSON
    # instead of uploaded Excel files.
    source_rows = _form_optional_str(form, "source_rows")
    target_rows = _form_optional_str(form, "target_rows")
    # Date Range Alignment: which records to reconcile against.
    date_scope = _form_str(form, "date_scope", "overlap")
    override_no_overlap = _form_bool(form, "override_no_overlap")

    # Parse optional sheet names.
    src_sheet = str(sheet_name_source).strip() or None
    tgt_sheet = str(sheet_name_target).strip() or None

    # scenarios can arrive as `scenarios` or `scenario_list`
    raw_scenarios = scenarios if scenarios is not None else scenario_list
    scenarios_list = _parse_scenarios(raw_scenarios)

    # Resolve each side independently so any connector combination works
    # (Excel upload and/or SAP fetch on either side).
    source_df, _source_bytes, _source_name = _resolve_side(
        source_rows, source_file, src_sheet, "source"
    )
    target_df, original_target_bytes, target_name = _resolve_side(
        target_rows, target_file, tgt_sheet, "target"
    )
    output_name = target_name or "reconciliation.xlsx"

    # Date Range Alignment: detect date columns, compute source vs target ranges
    # and their overlap, and (by default) filter both datasets to that overlap
    # before any comparison work runs. Runs regardless of scope so the
    # response can always report what the ranges/overlap look like.
    date_alignment = build_alignment(source_df, target_df)
    scope = (date_scope or "overlap").strip().lower()
    if scope not in {"overlap", "full"}:
        raise HTTPException(status_code=400, detail=f"Invalid date_scope: {date_scope!r}. Allowed: overlap, full")

    if scope == "overlap":
        src_date_col = date_alignment["source_date_column"]
        tgt_date_col = date_alignment["target_date_column"]

        if src_date_col and tgt_date_col:
            if date_alignment["has_overlap"]:
                overlap = date_alignment["overlap"]
                start = pd.Timestamp(overlap["start"])
                end = pd.Timestamp(overlap["end"])
                source_df = filter_to_window(source_df, src_date_col, start, end)
                target_df = filter_to_window(target_df, tgt_date_col, start, end)
            elif not override_no_overlap:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": "No overlapping date range between source and target datasets.",
                        "no_overlap": True,
                        "date_alignment": date_alignment,
                    },
                )
            # else: no overlap but user explicitly overrode — proceed on full data.
        # else: a date column couldn't be detected on one/both sides — skip
        # filtering and proceed on the full data (nothing to align on).

    # Parse mapping. Prefer mapping_json; allow fallback to `mapping`
    # (legacy/alternative field name). If neither is supplied, auto-detect
    # using the same auto-mapper the Excel flow's /automap route uses.
    raw_mapping = mapping_json or mapping
    if raw_mapping:
        mapping = _parse_mapping(raw_mapping)
    else:
        mapping = auto_map_columns(source_df, target_df)["mapping"]

    # TEMP DEBUG: validate mapping parsed shape (do NOT log file contents)
    try:
        kf = mapping.get("key_fields", [])
        cf = mapping.get("compare_fields", [])
        logger.info(
            "Reconcile mapping parsed keys: %s; key_fields=%s compare_fields=%s",
            list(mapping.keys()),
            len(kf) if isinstance(kf, list) else "?",
            len(cf) if isinstance(cf, list) else "?",
        )
    except Exception:
        logger.info("Received mapping but failed to compute field counts")

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

    # Generate output Excel. `original_target_path=None` is handled
    # gracefully by write_annotated_excel (no width-map template to copy).
    output_sheet_name = "Compared_Output"

    output_bytes_io = write_annotated_excel(
        result_df,
        original_target_path=BytesIO(original_target_bytes) if original_target_bytes else None,
        sheet_name=output_sheet_name,
    )

    file_id = uuid4().hex
    filename = get_output_filename(output_name)

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
        "date_alignment": date_alignment,
        "date_scope_applied": scope,
    }

