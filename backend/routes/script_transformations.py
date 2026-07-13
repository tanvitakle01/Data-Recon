"""Transformation Preview + Approval API (USE_SCRIPT_TRANSFORMATIONS flow).

    generate  → script (Groq → deterministic fallback) + static validation
    preview   → sandbox execution snapshot: summary, diffs, transformed rows
    approve / reject → user decision on the transformed DATA
    run       → production execution of the hash-pinned approved script,
                then the unchanged deterministic reconciliation

The script text itself is an internal artifact — it is stored and audited but
never returned by these endpoints.
"""

from __future__ import annotations

import io
import time
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.recon_engine import service
from backend.recon_engine.config import get_settings
from backend.recon_engine.llm import get_last_llm_outcome, reset_llm_outcome
from backend.recon_engine.models.rules import BusinessRule, BusinessRules
from backend.recon_engine.scripting import ScriptExecutionError
from backend.recon_engine.storage import run_store, script_store, snapshot_store

router = APIRouter(prefix="/api/recon/transformations", tags=["recon-transformations"])

_PREVIEW_ROW_LIMIT = 500


class GenerateRequest(BaseModel):
    # Parsed mapping-sheet payload (dict from /mapping-sheet/parse) or plain rows.
    mapping_sheet: dict[str, Any] | list[dict[str, Any]] = Field(default_factory=list)
    # Legacy free-text instructions; used only when the structured lists below
    # are all empty — see BusinessRules / service.generate_transformation_script.
    rules: str = ""
    transformation_rules: list[BusinessRule] = Field(default_factory=list)
    matching_rules: list[BusinessRule] = Field(default_factory=list)
    filter_rules: list[BusinessRule] = Field(default_factory=list)
    source_schema: list[str]
    target_schema: list[str]
    actor: str = "system"

    def business_rules(self) -> BusinessRules:
        return BusinessRules(
            transformation_rules=self.transformation_rules,
            matching_rules=self.matching_rules,
            filter_rules=self.filter_rules,
        )


class PreviewRequest(BaseModel):
    script_id: str
    rows: list[dict[str, Any]]
    actor: str = "system"


class ApproveRequest(BaseModel):
    preview_id: str
    approved_by: str


class RejectRequest(BaseModel):
    preview_id: str
    actor: str = "system"
    reason: str | None = None


class ScriptRunRequest(BaseModel):
    approval_id: str
    source_snapshot_id: str
    target_snapshot_id: str
    business_key: list[dict[str, str]]
    compare_fields: list[dict[str, Any]] = Field(default_factory=list)
    options: dict[str, Any] | None = None
    comparison_type: str = "custom"
    source_type: str = "excel"
    target_type: str = "excel"
    actor: str = "system"


@router.get("/mode")
def get_mode() -> dict[str, Any]:
    """Feature-flag discovery for the frontend."""
    return {"use_script_transformations": get_settings().use_script_transformations}


@router.post("/generate")
def generate(req: GenerateRequest) -> dict[str, Any]:
    """Generate a transformation script from the parsed mapping sheet + rules.

    Groq failures degrade to the deterministic fallback generator — this
    endpoint never fails because the LLM is unavailable.
    """
    if not req.source_schema or not req.target_schema:
        raise HTTPException(status_code=400, detail="source_schema and target_schema are required.")

    reset_llm_outcome()  # clear any prior provider outcome for this request
    script, validation, degraded_reason = service.generate_transformation_script(
        parsed_mapping=req.mapping_sheet,
        rules=req.rules,
        business_rules=req.business_rules(),
        source_schema=req.source_schema,
        target_schema=req.target_schema,
        actor=req.actor,
    )
    if not validation["ok"]:
        # Both generators produced something unsafe/broken — the fallback is
        # deterministic, so this indicates a bug worth surfacing loudly.
        raise HTTPException(
            status_code=422,
            detail="Generated script failed static validation: "
            + "; ".join(validation["errors"]),
        )
    outcome = get_last_llm_outcome()
    return {
        "script": script.public_dict(),
        "validation": validation,
        "degraded": degraded_reason is not None,
        "degraded_reason": degraded_reason,
        # LLM provider failover surface (spec points 4, 5, 6).
        "provider": (outcome.provider_used if outcome and outcome.provider_used else script.generated_by.value),
        "preferred_provider": outcome.preferred if outcome else "groq",
        "fallback": bool(outcome and outcome.fallback_occurred),
        "provider_notice": outcome.notice if outcome else None,
    }


def _summary_line(preview) -> str:
    n_cols = len(preview.modified_columns)
    return (
        f"{n_cols} column{'s' if n_cols != 1 else ''} transformed · "
        f"{preview.affected_rows} row{'s' if preview.affected_rows != 1 else ''} affected"
    )


def _preview_payload(preview, script, transformed_df: pd.DataFrame) -> dict[str, Any]:
    limited = transformed_df.head(_PREVIEW_ROW_LIMIT)
    rows = limited.astype(object).where(pd.notna(limited), None).to_dict(orient="records")
    return {
        "preview_id": preview.preview_id,
        "script_id": preview.script_id,
        "generated_by": script.generated_by.value,
        "confidence": script.confidence,
        "status": preview.status.value,
        "summary": {
            "text": _summary_line(preview),
            "columns_transformed": len(preview.modified_columns),
            "rows_affected": preview.affected_rows,
            "total_rows": preview.row_count,
        },
        "explanation": script.explanation,
        "modified_columns": preview.modified_columns,
        "row_diffs": preview.row_diffs,
        "transformed_rows": rows,
        "transformed_rows_truncated": preview.row_count > _PREVIEW_ROW_LIMIT,
        "execution_log": preview.execution_log,
    }


@router.post("/preview")
def preview(req: PreviewRequest) -> dict[str, Any]:
    """Sandbox-execute the script on sample rows and store the preview snapshot."""
    if not req.rows:
        raise HTTPException(status_code=400, detail="No sample rows to preview.")
    try:
        preview_record, script = service.preview_transformation(
            req.script_id, pd.DataFrame(req.rows), actor=req.actor
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ScriptExecutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    transformed = script_store.load_preview_frame(preview_record.preview_id)
    return _preview_payload(preview_record, script, transformed)


@router.get("/preview/{preview_id}")
def get_preview(preview_id: str) -> dict[str, Any]:
    preview_record = script_store.get_preview(preview_id)
    if preview_record is None:
        raise HTTPException(status_code=404, detail="Unknown preview.")
    script = script_store.get_script(preview_record.script_id)
    if script is None:
        raise HTTPException(status_code=404, detail="Preview's script no longer exists.")
    transformed = script_store.load_preview_frame(preview_id)
    return _preview_payload(preview_record, script, transformed)


@router.get("/preview/{preview_id}/download")
def download_preview(preview_id: str) -> StreamingResponse:
    """Download the full transformed preview as CSV."""
    try:
        transformed = script_store.load_preview_frame(preview_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown preview.")
    buf = io.StringIO()
    transformed.to_csv(buf, index=False)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{preview_id}.csv"'},
    )


@router.post("/approve")
def approve(req: ApproveRequest) -> dict[str, Any]:
    """Approve the transformed data (not the code). Pins the script hash."""
    try:
        approval = service.approve_transformation_preview(
            req.preview_id, approved_by=req.approved_by
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"approval": approval.model_dump(mode="json")}


@router.post("/reject")
def reject(req: RejectRequest) -> dict[str, Any]:
    try:
        service.reject_transformation_preview(
            req.preview_id, actor=req.actor, reason=req.reason
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True, "preview_id": req.preview_id, "status": "rejected"}


@router.post("/run")
def run(req: ScriptRunRequest) -> dict[str, Any]:
    """Production execution: approved script → Shadow_Source → reconciliation."""
    started = time.perf_counter()
    try:
        out = service.run_reconciliation_with_script(
            approval_id=req.approval_id,
            source_snapshot_id=req.source_snapshot_id,
            target_snapshot_id=req.target_snapshot_id,
            business_key=req.business_key,
            compare_fields=req.compare_fields,
            options=req.options,
            comparison_type=req.comparison_type,
            source_type=req.source_type,
            target_type=req.target_type,
            actor=req.actor,
        )
    except (ValueError, ScriptExecutionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    # Same enrichment shape as /api/recon/runs so the results UI can render it.
    out["runtime_ms"] = int((time.perf_counter() - started) * 1000)
    run_record = run_store.get_run(out["run_id"])
    if run_record is not None:
        out["run"] = run_record.model_dump(mode="json")
    transformation = out.get("transformation", {})
    out["contract"] = {
        "contract_id": f"script:{transformation.get('script_id', '?')}",
        "contract_version": 1,
        "compiler": transformation.get("generated_by", "script"),
        "approved_by": transformation.get("approved_by"),
        "approved_at": None,
    }
    for key, snap_id in (
        ("source_snapshot", req.source_snapshot_id),
        ("target_snapshot", req.target_snapshot_id),
    ):
        snap = snapshot_store.get_snapshot(snap_id)
        if snap is not None:
            out[key] = snap.model_dump(mode="json")
    return out
