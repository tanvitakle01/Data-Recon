"""Persistence for the script-transformation flow.

Three append-oriented tables: generated scripts (internal artifacts, pinned by
hash), preview snapshots (the transformed DATA users review — frame payload on
disk next to results), and approvals (user sign-off binding a preview to the
exact script hash). Previews get a status update on approve/reject; script and
approval rows are never mutated.
"""

from __future__ import annotations

import json
import uuid

import pandas as pd

from backend.recon_engine.config import get_settings
from backend.recon_engine.scripting.models import (
    GeneratedBy,
    PreviewStatus,
    ScriptApproval,
    ScriptPreview,
    TransformationScript,
)
from backend.recon_engine.storage import frames
from backend.recon_engine.storage.db import main_db


# ── scripts ──────────────────────────────────────────────────────────────────

def save_script(script: TransformationScript, *, validation: dict) -> TransformationScript:
    with main_db() as conn:
        conn.execute(
            """INSERT INTO transformation_scripts
               (script_id, generated_by, generated_at, explanation_json, script_text,
                script_hash, source_columns_json, target_columns_json, confidence,
                validation_ok, validation_json, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                script.script_id, script.generated_by.value, script.generated_at.isoformat(),
                json.dumps(script.explanation), script.script, script.script_hash,
                json.dumps(script.source_columns), json.dumps(script.target_columns),
                script.confidence, 1 if validation.get("ok") else 0,
                json.dumps(validation), script.created_by,
            ),
        )
    return script


def get_script(script_id: str) -> TransformationScript | None:
    with main_db() as conn:
        row = conn.execute(
            "SELECT * FROM transformation_scripts WHERE script_id = ?", (script_id,)
        ).fetchone()
    if row is None:
        return None
    return TransformationScript(
        script_id=row["script_id"],
        generated_by=GeneratedBy(row["generated_by"]),
        generated_at=row["generated_at"],
        explanation=json.loads(row["explanation_json"]),
        script=row["script_text"],
        script_hash=row["script_hash"],
        source_columns=json.loads(row["source_columns_json"]),
        target_columns=json.loads(row["target_columns_json"]),
        confidence=row["confidence"],
        created_by=row["created_by"],
    )


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
    settings = get_settings()
    settings.ensure_dirs()

    preview_id = "preview_" + uuid.uuid4().hex
    storage_path = str(settings.previews_data_dir / f"{preview_id}.json")
    frames.write_frame(transformed_df, storage_path)

    preview = ScriptPreview(
        preview_id=preview_id,
        script_id=script.script_id,
        script_hash=script.script_hash,
        row_count=int(transformed_df.shape[0]),
        affected_rows=affected_rows,
        modified_columns=modified_columns,
        row_diffs=row_diffs,
        execution_log=execution_log,
        storage_path=storage_path,
        created_by=created_by,
    )
    with main_db() as conn:
        conn.execute(
            """INSERT INTO script_previews
               (preview_id, script_id, script_hash, row_count, affected_rows,
                modified_columns_json, row_diffs_json, execution_log_json,
                storage_path, status, created_at, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                preview.preview_id, preview.script_id, preview.script_hash,
                preview.row_count, preview.affected_rows,
                json.dumps(preview.modified_columns), json.dumps(preview.row_diffs),
                json.dumps(preview.execution_log), preview.storage_path,
                preview.status.value, preview.created_at.isoformat(), preview.created_by,
            ),
        )
    return preview


def get_preview(preview_id: str) -> ScriptPreview | None:
    with main_db() as conn:
        row = conn.execute(
            "SELECT * FROM script_previews WHERE preview_id = ?", (preview_id,)
        ).fetchone()
    if row is None:
        return None
    return ScriptPreview(
        preview_id=row["preview_id"],
        script_id=row["script_id"],
        script_hash=row["script_hash"],
        row_count=row["row_count"],
        affected_rows=row["affected_rows"],
        modified_columns=json.loads(row["modified_columns_json"]),
        row_diffs=json.loads(row["row_diffs_json"]),
        execution_log=json.loads(row["execution_log_json"]),
        storage_path=row["storage_path"],
        status=PreviewStatus(row["status"]),
        created_at=row["created_at"],
        created_by=row["created_by"],
    )


def load_preview_frame(preview_id: str) -> pd.DataFrame:
    preview = get_preview(preview_id)
    if preview is None:
        raise KeyError(f"Unknown preview '{preview_id}'.")
    return frames.read_frame(preview.storage_path)


def set_preview_status(preview_id: str, status: PreviewStatus) -> None:
    with main_db() as conn:
        conn.execute(
            "UPDATE script_previews SET status = ? WHERE preview_id = ?",
            (status.value, preview_id),
        )


# ── approvals ────────────────────────────────────────────────────────────────

def save_approval(approval: ScriptApproval) -> ScriptApproval:
    with main_db() as conn:
        conn.execute(
            """INSERT INTO script_approvals
               (approval_id, preview_snapshot_id, script_id, script_hash,
                approved_by, approved_at)
               VALUES (?,?,?,?,?,?)""",
            (
                approval.approval_id, approval.preview_snapshot_id, approval.script_id,
                approval.script_hash, approval.approved_by, approval.approved_at.isoformat(),
            ),
        )
    return approval


def get_approval(approval_id: str) -> ScriptApproval | None:
    with main_db() as conn:
        row = conn.execute(
            "SELECT * FROM script_approvals WHERE approval_id = ?", (approval_id,)
        ).fetchone()
    if row is None:
        return None
    return ScriptApproval(
        approval_id=row["approval_id"],
        preview_snapshot_id=row["preview_snapshot_id"],
        script_id=row["script_id"],
        script_hash=row["script_hash"],
        approved_by=row["approved_by"],
        approved_at=row["approved_at"],
    )
