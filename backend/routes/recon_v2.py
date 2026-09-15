"""Runtime reconciliation API: snapshots, runs, results, audit, TTL cleanup.

Runtime reconciliation involves NO LLM — it executes an already-approved
contract through the deterministic engine and persists everything (snapshots,
shadow, results, audit) for a fully auditable, reproducible workflow.
"""

from __future__ import annotations

import json
import time
from io import BytesIO
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Request, Response
from starlette.datastructures import UploadFile
from pydantic import BaseModel, Field

from backend.excel_comparator.core.loader import load_excel
from backend.recon_engine import service
from backend.recon_engine.config import get_settings
from backend.recon_engine.models.snapshot import RawLayer
from backend.recon_engine.storage import (
    audit_store,
    contract_store,
    result_store,
    run_store,
    snapshot_store,
)

router = APIRouter(prefix="/api/recon", tags=["recon-runtime"])

# SAP-fetched datasets (S/4, IBP) travel to /snapshots/upload as a single
# `rows` JSON form field that routinely exceeds Starlette's default 1MB
# per-part cap ("Part exceeded maximum size of 1024KB."). Parse the multipart
# form manually with a much higher per-part limit — mirrors routes/reconcile.py.
_MAX_PART_SIZE = 64 * 1024 * 1024  # 64MB per field


def _form_str(form, key: str, default: str | None = None) -> str | None:
    value = form.get(key)
    if value is None or isinstance(value, UploadFile):
        return default
    return str(value)


def _form_upload(form, key: str) -> UploadFile | None:
    value = form.get(key)
    return value if isinstance(value, UploadFile) else None


class SnapshotRequest(BaseModel):
    rows: list[dict[str, Any]]
    layer: str = Field(..., description="'Raw_Source' or 'Raw_Target'.")
    source_type: str
    comparison_type: str | None = None
    created_by: str = "system"
    lineage: dict[str, Any] = Field(default_factory=dict)


class RunRequest(BaseModel):
    contract_id: str
    contract_version: int | None = None
    source_snapshot_id: str
    target_snapshot_id: str
    # Set by the Review-Changes checkpoint to the fingerprint of the shadow the
    # user approved. When present the run verifies the freshly-built shadow
    # matches it, otherwise 409s (contract/source changed since review).
    expected_shadow_fingerprint: str | None = None
    # None (default) -> anchor date_window_filter/relative_date_reassign to
    # wall-clock "now", the correct behavior for a normal live run. Pass an
    # ISO date (e.g. "2026-09-03") to replay/validate this contract as if it
    # ran on that day instead — for reconciling against a HISTORICAL target
    # snapshot captured on a different calendar day than today, which a
    # wall-clock-anchored rollforward rule can never match. Must match
    # whatever anchor_date the Review-Changes preview used, if one was given
    # there, or the shadow-fingerprint check below will 409.
    anchor_date: str | None = None
    actor: str = "system"


class ShadowPreviewRequest(BaseModel):
    contract_id: str
    contract_version: int | None = None
    source_snapshot_id: str
    target_snapshot_id: str | None = None
    # None -> fall back to the configured RECON_PREVIEW_ROWS sample size. Only
    # this sample is embedded in the response; the full transformed dataset stays
    # on disk and is referenced by snapshot/fingerprint, not shipped to the UI.
    preview_rows: int | None = None
    target_preview_rows: int | None = None
    # See RunRequest.anchor_date — the run this preview is reviewed for must
    # pass the same value.
    anchor_date: str | None = None
    actor: str = "system"


class RecipePreviewRequest(BaseModel):
    # The unsaved draft contract being authored in the recipe editor. Must carry
    # `operations` (+ schemas/options); business_key/compare_fields are optional
    # for a preview since it only builds the Shadow_Source, not a reconciliation.
    draft: dict[str, Any]
    # Source sample: either a persisted snapshot (sampled server-side) or inline
    # rows already sampled by the caller. Exactly one is expected.
    source_snapshot_id: str | None = None
    source_rows: list[dict[str, Any]] | None = None
    # "Preview up to this step" (authored index): later ops are treated as
    # disabled. None = preview the whole recipe.
    active_step_index: int | None = None
    preview_rows: int | None = None
    actor: str = "system"


class ChainRowCountsRequest(BaseModel):
    # The unsaved draft whose chain is walked node by node. Only `operations`
    # (+ schemas/options) matter — no reconciliation is performed.
    draft: dict[str, Any]
    # Source: a persisted snapshot (preferred — the FULL frame, so an empty
    # result is real and not a thin-sample artifact) or inline rows.
    source_snapshot_id: str | None = None
    source_rows: list[dict[str, Any]] | None = None
    actor: str = "system"


@router.post("/chain-row-counts")
def chain_row_counts(req: ChainRowCountsRequest) -> dict[str, Any]:
    """Per-node shadow row counts for a draft chain — read-only.

    Backs the auto-approve gate's "no node produces an empty frame" condition:
    it runs the deterministic executor once per enabled node, on the prefix
    ending at that node, and reports each node's output row count. Creates no
    run, shadow, or result."""
    try:
        return service.build_chain_row_counts(
            draft=req.draft,
            source_snapshot_id=req.source_snapshot_id,
            source_rows=req.source_rows,
            actor=req.actor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/recipe-preview")
def recipe_preview(req: RecipePreviewRequest) -> dict[str, Any]:
    """Live, read-only before/after preview for the recipe editor.

    Runs an UNSAVED draft's operations (optionally truncated at
    ``active_step_index``) against a sample of the raw source via the same
    deterministic executor + diff engine a real run uses. Creates no run,
    shadow, or result — pure read."""
    default_rows = get_settings().preview_rows
    try:
        return service.build_recipe_preview(
            draft=req.draft,
            source_snapshot_id=req.source_snapshot_id,
            source_rows=req.source_rows,
            active_step_index=req.active_step_index,
            preview_rows=req.preview_rows if req.preview_rows is not None else default_rows,
            actor=req.actor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/snapshots")
def create_snapshot(req: SnapshotRequest) -> dict[str, Any]:
    try:
        layer = RawLayer(req.layer)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid layer '{req.layer}'.")
    if not req.rows:
        raise HTTPException(status_code=400, detail="No rows to snapshot.")

    snap = service.ingest_snapshot(
        pd.DataFrame(req.rows),
        layer=layer,
        source_type=req.source_type,
        comparison_type=req.comparison_type,
        created_by=req.created_by,
        lineage=req.lineage,
    )
    return {"snapshot": snap.model_dump(mode="json")}


@router.post("/snapshots/upload")
async def create_snapshot_upload(request: Request) -> dict[str, Any]:
    """Multipart snapshot ingestion for the wizard.

    Accepts either an uploaded Excel/CSV ``file`` (datasets the browser holds
    only as a file handle) or a ``rows`` JSON array (SAP-fetched datasets).
    Either way the data lands in the same immutable raw layer via
    ``service.ingest_snapshot`` — this is just a transport adapter.

    The form is parsed manually with a raised ``max_part_size`` so large
    SAP-fetched ``rows`` payloads don't trip Starlette's 1MB per-part cap.
    """
    form = await request.form(max_part_size=_MAX_PART_SIZE)

    layer = _form_str(form, "layer")
    source_type = _form_str(form, "source_type")
    comparison_type = _form_str(form, "comparison_type")
    created_by = _form_str(form, "created_by", "system")
    sheet_name = _form_str(form, "sheet_name")
    file = _form_upload(form, "file")
    rows = _form_str(form, "rows")

    if not layer:
        raise HTTPException(status_code=400, detail="Missing 'layer'.")
    if not source_type:
        raise HTTPException(status_code=400, detail="Missing 'source_type'.")

    try:
        layer_enum = RawLayer(layer)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid layer '{layer}'.")

    lineage: dict[str, Any] = {"ingest": "wizard"}

    if file is not None:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
        filename = file.filename or "upload"
        try:
            if filename.lower().endswith(".csv"):
                df = pd.read_csv(BytesIO(content), dtype=object)
                df.columns = [str(c).strip() for c in df.columns]
            else:
                payload = load_excel(BytesIO(content), sheet_name=sheet_name)
                df = payload["df"]
                lineage["sheet"] = payload["active_sheet"]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        lineage["filename"] = filename
    elif rows:
        try:
            parsed_rows = json.loads(rows)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="'rows' is not valid JSON.")
        if not isinstance(parsed_rows, list) or not parsed_rows:
            raise HTTPException(status_code=400, detail="'rows' must be a non-empty JSON array.")
        df = pd.DataFrame(parsed_rows)
    else:
        raise HTTPException(status_code=400, detail="Provide either 'file' or 'rows'.")

    if df.empty:
        raise HTTPException(status_code=400, detail="No rows to snapshot.")

    snap = service.ingest_snapshot(
        df,
        layer=layer_enum,
        source_type=source_type,
        comparison_type=comparison_type,
        created_by=created_by,
        lineage=lineage,
    )
    return {"snapshot": snap.model_dump(mode="json")}


@router.get("/snapshots")
def list_snapshots(layer: str | None = None) -> dict[str, Any]:
    layer_enum = None
    if layer is not None:
        try:
            layer_enum = RawLayer(layer)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid layer '{layer}'.")
    snaps = snapshot_store.list_snapshots(layer_enum)
    return {"snapshots": [s.model_dump(mode="json") for s in snaps]}


@router.get("/snapshots/{snapshot_id}")
def get_snapshot(snapshot_id: str) -> dict[str, Any]:
    snap = snapshot_store.get_snapshot(snapshot_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="Unknown snapshot.")
    return {"snapshot": snap.model_dump(mode="json")}


@router.post("/shadow-preview")
def shadow_preview(req: ShadowPreviewRequest) -> dict[str, Any]:
    """Review-Changes checkpoint: build the Shadow_Source from an approved
    contract + source snapshot and return before/after data, diffs, an optional
    target preview, and the shadow fingerprint. Read-only — creates no run."""
    default_rows = get_settings().preview_rows
    try:
        return service.build_shadow_preview(
            contract_id=req.contract_id,
            contract_version=req.contract_version,
            source_snapshot_id=req.source_snapshot_id,
            target_snapshot_id=req.target_snapshot_id,
            preview_rows=req.preview_rows if req.preview_rows is not None else default_rows,
            target_preview_rows=(
                req.target_preview_rows
                if req.target_preview_rows is not None
                else default_rows
            ),
            anchor_date=req.anchor_date,
            actor=req.actor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/runs")
def create_run(req: RunRequest) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        out = service.run_reconciliation(
            contract_id=req.contract_id,
            contract_version=req.contract_version,
            source_snapshot_id=req.source_snapshot_id,
            target_snapshot_id=req.target_snapshot_id,
            expected_shadow_fingerprint=req.expected_shadow_fingerprint,
            anchor_date=req.anchor_date,
            actor=req.actor,
        )
    except service.ShadowFingerprintMismatch as exc:
        # 409 Conflict — the reviewed shadow is stale; the UI must re-review.
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    # Enrich with the audit metadata the results UI displays (contract used,
    # snapshot provenance, execution stats). Pure reads — the run is done.
    out["runtime_ms"] = int((time.perf_counter() - started) * 1000)
    run = run_store.get_run(out["run_id"])
    if run is not None:
        out["run"] = run.model_dump(mode="json")
        contract = contract_store.get_contract(run.contract_id, run.contract_version)
        if contract is not None:
            out["contract"] = {
                "contract_id": contract.contract_id,
                "contract_version": contract.contract_version,
                "compiler": contract.compiler,
                "approved_by": contract.approved_by,
                "approved_at": contract.approved_at.isoformat() if contract.approved_at else None,
            }
    for key, snap_id in (
        ("source_snapshot", req.source_snapshot_id),
        ("target_snapshot", req.target_snapshot_id),
    ):
        snap = snapshot_store.get_snapshot(snap_id)
        if snap is not None:
            out[key] = snap.model_dump(mode="json")
    return out


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    run = run_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown run.")
    return {"run": run.model_dump(mode="json")}


class DateAlignmentRequest(BaseModel):
    source_snapshot_id: str
    target_snapshot_id: str


@router.post("/date-alignment")
def date_alignment(req: DateAlignmentRequest) -> dict[str, Any]:
    """Pre-run date-overlap diagnostic between two raw snapshots: source/target
    date ranges, overlap window, overlap %, and included/excluded row counts."""
    try:
        alignment = service.compute_snapshot_date_alignment(
            req.source_snapshot_id, req.target_snapshot_id
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"alignment": alignment}


@router.get("/runs/{run_id}/date-alignment")
def run_date_alignment(run_id: str) -> dict[str, Any]:
    """POST-run date-overlap diagnostic: the same window/overlap analysis as
    ``/date-alignment`` above, but between the run's actual Shadow_Source
    (post-transform — reflects date_window_filter/relative_date_reassign)
    and its Raw_Target, rather than the two raw uploads pre-transform.

    This is what actually explains a run with an unexpectedly high
    missing_in_target/extra_in_target count when a date-dependent transform
    is involved: e.g. a rollforward rule anchored to wall-clock "now" run
    against a target snapshot captured on an earlier day will show ZERO date
    overlap here even though the pre-transform snapshots (checked by
    ``/date-alignment``) overlap fine — the mismatch only appears after the
    transform, which this endpoint is the only diagnostic that actually
    replays."""
    run = run_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown run.")
    return {"alignment": service.compute_run_date_alignment(run)}


@router.get("/runs/{run_id}/comparison.xlsx")
def download_comparison(run_id: str) -> Response:
    """Download the run's colour-coded comparison workbook (.xlsx): three
    sheets — Summary (per-category counts/% of total, trimmed run info, and
    three pie charts), All Records (every match/mismatch/missing/extra row
    stacked into one flat, status-coloured table), and Mapping Details (every
    Material↔PRDID and Plant↔LOCID value-pairing decision). Read-only — not
    re-run."""
    try:
        content = service.build_comparison_workbook(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    filename = f"comparison_{run_id}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/results/{result_id}")
def get_result(result_id: str, preview: int = 200) -> dict[str, Any]:
    result = result_store.get_result(result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown result.")
    detail = result_store.load_result_frame_any(result_id).head(max(0, preview))
    rows = detail.astype(object).where(pd.notna(detail), None).to_dict(orient="records")
    return {"result": result.model_dump(mode="json"), "preview_rows": rows}


@router.get("/audit")
def get_audit(entity_id: str | None = None) -> dict[str, Any]:
    events = audit_store.list_events(entity_id)
    return {"events": [e.model_dump(mode="json") for e in events]}


@router.post("/shadows/cleanup")
def cleanup_shadows() -> dict[str, Any]:
    removed = service.cleanup_expired_shadows()
    return {"removed": removed, "count": len(removed)}
