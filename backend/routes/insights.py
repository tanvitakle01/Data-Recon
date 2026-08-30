from __future__ import annotations

import logging
import re
from io import BytesIO
from typing import Any

import pandas as pd
from fastapi import APIRouter, File, UploadFile, HTTPException, Body, Response

from backend.ai.insight_engine import InsightEngine
from backend.excel_comparator.core.loader import load_excel
from backend.recon_engine import service as recon_service
from backend.recon_engine.reporting.insights_pdf import build_insights_pdf

logger = logging.getLogger(__name__)

router = APIRouter()

# Reuse the same in-memory store used by backend/routes/reconcile.py
try:
    from backend.routes.reconcile import _FILE_STORE  # type: ignore
except Exception:  # pragma: no cover
    _FILE_STORE: dict[str, dict[str, Any]] = {}

# Same three user-facing statuses/labels as
# backend.recon_engine.service._SUMMARY_BUCKETS, keyed off the legacy
# excel_comparator "Remarks" phrases instead of a V2 run's `classification`
# column — lets a raw compared-output upload render through the exact same
# SimpleInsightsView as a persisted contract run.
_RESULT_BUCKETS = [("match", "Match", "MATCH"), ("quantity_mismatch", "Quantity Mismatch", "QUANTITY MISMATCH"), ("mismatch", "Mismatch", "MISMATCH")]
_DELTA_RE = re.compile(r"Delta:\s*(-?\d+(?:\.\d+)?)")


def _status_for_remark(remark: str) -> str:
    if re.search(r"QTY MISMATCH", remark, re.IGNORECASE):
        return "QUANTITY MISMATCH"
    if re.search(r"MISSING IN TARGET|EXTRA IN TARGET", remark, re.IGNORECASE):
        return "MISMATCH"
    return "MATCH"


def _empty_simple_insights() -> dict[str, Any]:
    return {
        "runId": None,
        "total": 0,
        "results": [{"key": k, "label": label, "status": status, "count": 0, "pct": 0.0} for k, label, status in _RESULT_BUCKETS],
        "quantityVariance": None,
        "mappings": [],
        "exceptions": {"columns": [], "rows": []},
    }


def _simple_insights_from_remarks_df(df: pd.DataFrame) -> dict[str, Any]:
    """Builds the same payload shape as
    :func:`backend.recon_engine.service.build_simple_insights` (results
    breakdown, quantity variance, exceptions) from a legacy excel_comparator
    "Remarks" column, so ``/insights/from-file-id`` and ``/insights`` (raw
    upload) render through the same SimpleInsightsView as a persisted V2 run.
    No per-mapping match rates here — a raw upload carries no business-key
    value-mapping library to report on."""
    if df is None or df.empty or "Remarks" not in df.columns:
        return _empty_simple_insights()

    remarks = df["Remarks"].fillna("").astype(str)
    status_series = remarks.map(_status_for_remark)
    total = int(len(df))

    results = []
    for key, label, status in _RESULT_BUCKETS:
        count = int((status_series == status).sum())
        pct = round((count / total * 100.0), 1) if total else 0.0
        results.append({"key": key, "label": label, "status": status, "count": count, "pct": pct})

    total_units = 0.0
    largest = 0.0
    fields_affected = 0
    for raw in remarks.str.extract(_DELTA_RE, expand=False).dropna():
        try:
            magnitude = abs(float(raw))
        except ValueError:
            continue
        total_units += magnitude
        largest = max(largest, magnitude)
        fields_affected += 1
    quantity_variance = (
        {"totalUnits": round(total_units, 2), "largestUnit": round(largest, 2), "fieldsAffected": fields_affected}
        if fields_affected
        else None
    )

    exceptions_df = df.loc[status_series != "MATCH"].copy()
    exceptions_df.insert(0, "Status", status_series[status_series != "MATCH"])
    safe = exceptions_df.astype(object).where(pd.notna(exceptions_df), None)

    return {
        "runId": None,
        "total": total,
        "results": results,
        "quantityVariance": quantity_variance,
        "mappings": [],
        "exceptions": {"columns": list(safe.columns), "rows": safe.to_dict(orient="records")},
    }


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
        # Relies on the dataframe shape (incl. "Remarks" column) the legacy
        # excel_comparator writes.
        loaded = load_excel(BytesIO(file_bytes))
        df: pd.DataFrame = loaded["df"]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to load stored reconciliation output: {exc}")

    payload = _simple_insights_from_remarks_df(df)
    return {"success": True, "payload": payload}


@router.post("/insights/from-run-id")
async def generate_insights_from_run_id(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Generate insights for a persisted V2 reconciliation run.
    Expects: { "run_id": "<id from POST /api/recon/runs>" }"""
    run_id = body.get("run_id")
    if not run_id:
        raise HTTPException(status_code=400, detail="Missing run_id")

    try:
        payload = recon_service.build_simple_insights(str(run_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="Reconciliation run not found")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to build insights for run: {exc}")

    return {"success": True, "payload": payload}


@router.get("/insights/{run_id}/pdf")
def download_insights_pdf(run_id: str) -> Response:
    """Structured PDF export of a run's insights — same payload
    ``/insights/from-run-id`` returns, rendered as a printable report
    (see ``insights_pdf.py``)."""
    try:
        payload = recon_service.build_simple_insights(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Reconciliation run not found")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to build insights for run: {exc}")

    pdf_bytes = build_insights_pdf(payload, run_id=run_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="insights_{run_id}.pdf"'},
    )


_DRILLDOWN_DIMENSION_CANDIDATES = {
    "plant": ["plant", "werks", "location", "storagelocation"],
    "material": ["material", "matnr", "product", "item", "sku"],
    "date": ["deliverydate", "delivery date", "postingdate", "documentdate", "reqdeliverydate", "date"],
}

_DRILLDOWN_EXCEPTION_PATTERNS = {
    "Missing in Target": "MISSING IN TARGET",
    "Extra in Target": "EXTRA IN TARGET",
    "Quantity Mismatch": "QTY MISMATCH",
}

# Same exception types, keyed to the raw `classification` values
# build_enriched_detail carries (V2 runs have no "Remarks" column to
# pattern-match — "missing_in_source" (present in target only) is the V1
# "EXTRA IN TARGET" equivalent, see backend.recon_engine.service._CLASS_LABELS).
_DRILLDOWN_EXCEPTION_CLASSES = {
    "Missing in Target": "missing_in_target",
    "Extra in Target": "missing_in_source",
    "Quantity Mismatch": "mismatch",
}


@router.post("/insights/drilldown")
async def insights_drilldown(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """
    Row-level exploration for the Investigation Workspace. Reuses the same
    in-memory reconciliation output as /insights/from-file-id and the same
    column-detection logic as InsightEngine, instead of re-implementing
    dimension matching.

    Accepts either a V2 ``run_id`` (contract runs) or a V1 ``file_id`` (legacy
    Excel flow). Expects:
    { "run_id"|"file_id": str, "filters": {"dimension"?, "value"?, "exceptionType"?}, "limit"? }
    """
    run_id = body.get("run_id")
    file_id = body.get("file_id")

    if run_id:
        try:
            df: pd.DataFrame = recon_service.build_enriched_detail(str(run_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="Reconciliation run not found")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"Failed to build run dataset: {exc}")
    elif file_id:
        entry = _FILE_STORE.get(str(file_id))
        if not entry:
            raise HTTPException(status_code=404, detail="Reconciliation file_id not found")

        file_bytes = entry.get("bytes")
        if not isinstance(file_bytes, (bytes, bytearray)):
            raise HTTPException(status_code=404, detail="Stored dataset bytes not found for this file_id")

        try:
            loaded = load_excel(BytesIO(file_bytes))
            df = loaded["df"]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to load stored reconciliation output: {exc}")
    else:
        raise HTTPException(status_code=400, detail="Missing run_id or file_id")

    if df is None or df.empty:
        return {"success": True, "rows": [], "totalMatched": 0, "columns": []}

    filters = body.get("filters") or {}
    limit = int(body.get("limit") or 200)

    # field_diffs is a list column carried for variance rollups — not useful as a
    # raw table cell, and unhashable, so drop it from the drilldown view.
    working = df.drop(columns=["field_diffs"], errors="ignore")
    engine = InsightEngine()

    exception_type = filters.get("exceptionType")
    if exception_type and "Remarks" in working.columns:
        pattern = _DRILLDOWN_EXCEPTION_PATTERNS.get(exception_type)
        if pattern:
            remarks = working["Remarks"].fillna("").astype(str)
            working = working[remarks.str.contains(pattern, case=False, na=False, regex=True)]
    elif exception_type and "classification" in working.columns:
        raw_class = _DRILLDOWN_EXCEPTION_CLASSES.get(exception_type)
        if raw_class:
            working = working[working["classification"] == raw_class]

    dimension = str(filters.get("dimension") or "").lower()
    value = filters.get("value")
    candidates = _DRILLDOWN_DIMENSION_CANDIDATES.get(dimension)
    if candidates and value is not None:
        col = engine._detect_column(working, candidates)
        if col and col in working.columns:
            if dimension == "date":
                working = working[pd.to_datetime(working[col], errors="coerce").dt.date.astype(str) == str(value)]
            else:
                working = working[working[col].fillna("Unknown").astype(str) == str(value)]

    total_matched = int(len(working))
    preview = working.head(max(1, min(limit, 500)))
    safe_preview = preview.astype(object).where(pd.notna(preview), None)

    return {
        "success": True,
        "totalMatched": total_matched,
        "columns": list(safe_preview.columns),
        "rows": safe_preview.to_dict(orient="records"),
    }


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

    payload = _simple_insights_from_remarks_df(df)
    return {
        "success": True,
        "payload": payload,
    }
