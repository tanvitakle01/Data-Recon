"""Top-level orchestration for the three insights entry points — a run, an
uploaded results workbook, or (for the chat assistant/PDF) a run by id.
Every entry point funnels through `normalize.from_run`/`normalize.
from_workbook` and `facts.build_facts`, so a run-based view and an
uploaded-workbook view of the same underlying data always produce the same
numbers.
"""

from __future__ import annotations

import uuid
from typing import Any

from backend.recon_engine.insights import facts as facts_mod
from backend.recon_engine.insights import normalize
from backend.recon_engine.insights import query as query_mod
from backend.recon_engine.insights.normalize import NormalizedRecon, UnrecognizedWorkbookError
from backend.recon_engine.insights.pdf import build_insights_pdf

__all__ = [
    "UnrecognizedWorkbookError",
    "build_for_run",
    "build_for_upload",
    "pdf_for",
    "records_for",
    "records_csv_for",
]

# In-memory store for uploaded workbook bytes, keyed by a generated
# upload_id — same convention as backend.routes.reconcile's _FILE_STORE:
# nothing here is meant to survive a process restart, only to let a later
# drill-through/export/PDF call for an uploaded file skip re-uploading it.
_UPLOAD_STORE: dict[str, bytes] = {}


def _normalize_for(*, run_id: str | None, upload_id: str | None) -> NormalizedRecon:
    if run_id:
        return normalize.from_run(run_id)
    if upload_id:
        xlsx_bytes = _UPLOAD_STORE.get(upload_id)
        if xlsx_bytes is None:
            raise KeyError(f"Unknown upload_id '{upload_id}'.")
        normalized = normalize.from_workbook(xlsx_bytes)
        normalized.upload_id = upload_id
        return normalized
    raise ValueError("Either run_id or upload_id is required.")


def build_for_run(run_id: str) -> dict[str, Any]:
    return facts_mod.build_facts(normalize.from_run(run_id))


def build_for_upload(xlsx_bytes: bytes) -> dict[str, Any]:
    """Validates and normalizes the upload first — a rejected workbook is
    never stored — then stashes the bytes under a fresh `upload_id` so later
    drill-through/export/PDF calls don't need the file resent."""
    normalized = normalize.from_workbook(xlsx_bytes)
    upload_id = uuid.uuid4().hex
    _UPLOAD_STORE[upload_id] = xlsx_bytes
    normalized.upload_id = upload_id
    return facts_mod.build_facts(normalized)


def pdf_for(*, run_id: str | None = None, upload_id: str | None = None) -> bytes:
    normalized = _normalize_for(run_id=run_id, upload_id=upload_id)
    payload = facts_mod.build_facts(normalized)
    return build_insights_pdf(payload, run_id=run_id or upload_id)


def records_for(
    *,
    run_id: str | None = None,
    upload_id: str | None = None,
    filter_spec: dict[str, Any] | None,
    sort: str | None = None,
    sort_dir: str = "asc",
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    normalized = _normalize_for(run_id=run_id, upload_id=upload_id)
    return query_mod.filter_records(normalized, filter_spec, sort=sort, sort_dir=sort_dir, page=page, page_size=page_size)


def records_csv_for(
    *, run_id: str | None = None, upload_id: str | None = None, filter_spec: dict[str, Any] | None = None
) -> str:
    normalized = _normalize_for(run_id=run_id, upload_id=upload_id)
    return query_mod.records_to_csv(normalized, filter_spec)
