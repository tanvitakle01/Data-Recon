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


# V2 classification -> the V1 Remarks vocabulary the InsightEngine matches on.
# "missing_in_source" (present in target only) == V1 "EXTRA IN TARGET".
def build_insights_dataframe(run_id: str) -> pd.DataFrame:
    """Bridge a V2 reconciliation run into the DataFrame shape InsightEngine
    consumes. Reuses the run's enriched detail (named source/target field
    columns + structured field_diffs) and synthesises a ``Remarks`` column using
    the ALL-CAPS phrases the engine keys off, so the existing insights + cockpit
    work unchanged for contract runs."""
    from backend.recon_engine import service as recon_service

    enriched = recon_service.build_enriched_detail(run_id)
    if enriched.empty:
        return enriched

    remarks: list[str] = []
    for _, r in enriched.iterrows():
        cls = str(r.get("classification"))
        detail = str(r.get("detail") or "")
        if cls == "mismatch":
            diffs = r.get("field_diffs") if isinstance(r.get("field_diffs"), list) else []
            if diffs:
                d = diffs[0]
                remarks.append(
                    f"⚠️ QTY MISMATCH | Field: {d.get('field')} | "
                    f"Expected: {d.get('source_value')} | Actual: {d.get('target_value')} | "
                    f"Delta: {d.get('delta')}"
                )
            else:
                remarks.append("⚠️ QTY MISMATCH")
        elif cls == "missing_in_target":
            remarks.append(f"❌ MISSING IN TARGET | {detail}")
        elif cls == "missing_in_source":
            remarks.append(f"🔶 EXTRA IN TARGET | {detail}")
        else:
            remarks.append("✅ MATCH")

    df = enriched.copy()
    df["Remarks"] = remarks
    return df


def _quantity_variance_stats(df: pd.DataFrame) -> dict[str, Any] | None:
    """Absolute quantity variance rolled up from structured field diffs."""
    if "field_diffs" not in df.columns:
        return None
    total = 0.0
    largest = 0.0
    count = 0
    for diffs in df["field_diffs"]:
        if not isinstance(diffs, list):
            continue
        for d in diffs:
            delta = d.get("delta")
            if delta is None:
                continue
            magnitude = abs(float(delta))
            total += magnitude
            count += 1
            largest = max(largest, magnitude)
    if count == 0:
        return None
    return {
        "totalUnits": round(total, 2),
        "largestUnit": round(largest, 2),
        "fieldsAffected": count,
    }


def _generate_run_insights(run_id: str) -> dict[str, Any]:
    """Build the insight payload for a V2 run, enriched with quantity variance."""
    df = build_insights_dataframe(run_id)
    if df is None or df.empty:
        return InsightEngine().generate(pd.DataFrame())

    stats = _quantity_variance_stats(df)
    # field_diffs is a list column (unhashable) — the engine's duplicate
    # detection can't factorize it, so drop it before generating.
    engine_df = df.drop(columns=["field_diffs"], errors="ignore")
    payload = InsightEngine().generate(engine_df)
    if stats:
        payload["quantityVariance"] = stats
        cockpit = payload.get("cockpit")
        if isinstance(cockpit, dict) and isinstance(cockpit.get("exceptionLandscape"), dict):
            cockpit["exceptionLandscape"]["quantityVariance"] = stats
    return payload


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


@router.post("/insights/from-run-id")
async def generate_insights_from_run_id(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Generate insights for a persisted V2 reconciliation run.
    Expects: { "run_id": "<id from POST /api/recon/runs>" }"""
    run_id = body.get("run_id")
    if not run_id:
        raise HTTPException(status_code=400, detail="Missing run_id")

    try:
        payload = _generate_run_insights(str(run_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="Reconciliation run not found")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to build insights for run: {exc}")

    return {"success": True, "payload": payload}


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
            df: pd.DataFrame = build_insights_dataframe(str(run_id))
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
    pattern = _DRILLDOWN_EXCEPTION_PATTERNS.get(exception_type) if exception_type else None
    if pattern and "Remarks" in working.columns:
        remarks = working["Remarks"].fillna("").astype(str)
        working = working[remarks.str.contains(pattern, case=False, na=False, regex=True)]

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

    if df is None or df.empty:
        return InsightEngine().generate(pd.DataFrame())

    payload = InsightEngine().generate(df)
    return {
        "success": True,
        "payload": payload,
    }
