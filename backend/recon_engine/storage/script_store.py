"""Persistence for the script-transformation flow (in-memory).

Three stores: generated scripts (internal artifacts, pinned by hash), preview
snapshots (the transformed DATA users review), and approvals (user sign-off
binding a preview to the exact script hash). Previews get a status update on
approve/reject; script and approval rows are never mutated.
"""

from __future__ import annotations

import uuid

import pandas as pd

from backend.recon_engine.scripting.models import (
    PreviewStatus,
    ScriptApproval,
    ScriptPreview,
    TransformationScript,
)
from backend.recon_engine.storage import frames

_SCRIPTS: dict[str, TransformationScript] = {}
_PREVIEWS: dict[str, ScriptPreview] = {}
_APPROVALS: dict[str, ScriptApproval] = {}


# ── scripts ──────────────────────────────────────────────────────────────────

def save_script(script: TransformationScript, *, validation: dict) -> TransformationScript:
    _SCRIPTS[script.script_id] = script
    return script


def get_script(script_id: str) -> TransformationScript | None:
    return _SCRIPTS.get(script_id)


# ── previews ─────────────────────────────────────────────────────────────────

def create_preview(
    transformed_df: pd.DataFrame,
    *,
    script: TransformationScript,
    affected_rows: int,
    modified_columns: list[dict],
    row_diffs: list[dict],
    execution_log: list[str],
    created_by: str = "system",
) -> ScriptPreview:
    preview_id = "preview_" + uuid.uuid4().hex
    storage_key = f"script-preview:{preview_id}"
    frames.write_frame(transformed_df, storage_key)

    preview = ScriptPreview(
        preview_id=preview_id,
        script_id=script.script_id,
        script_hash=script.script_hash,
        row_count=int(transformed_df.shape[0]),
        affected_rows=affected_rows,
        modified_columns=modified_columns,
        row_diffs=row_diffs,
        execution_log=execution_log,
        storage_path=storage_key,
        created_by=created_by,
    )
    _PREVIEWS[preview_id] = preview
    return preview


def get_preview(preview_id: str) -> ScriptPreview | None:
    return _PREVIEWS.get(preview_id)


def load_preview_frame(preview_id: str) -> pd.DataFrame:
    preview = get_preview(preview_id)
    if preview is None:
        raise KeyError(f"Unknown preview '{preview_id}'.")
    return frames.read_frame(preview.storage_path)


def set_preview_status(preview_id: str, status: PreviewStatus) -> None:
    preview = _PREVIEWS.get(preview_id)
    if preview is not None:
        _PREVIEWS[preview_id] = preview.model_copy(update={"status": status})


# ── approvals ────────────────────────────────────────────────────────────────

def save_approval(approval: ScriptApproval) -> ScriptApproval:
    _APPROVALS[approval.approval_id] = approval
    return approval


def get_approval(approval_id: str) -> ScriptApproval | None:
    return _APPROVALS.get(approval_id)
