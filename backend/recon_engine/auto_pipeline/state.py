"""Graph state for the Auto-mode pipeline.

Kept as a plain TypedDict (LangGraph's native state shape) rather than a
pydantic model — nothing here needs validation beyond what each node already
enforces before writing to it.
"""

from __future__ import annotations

from typing import Any, TypedDict

STEP_NAMES = (
    "select_source",
    "select_target",
    "resolve_schema",
    "compile_contract",
    "plan_date_batches",
    "run_batches",
    "finalize",
)


class SideState(TypedDict, total=False):
    kind: str | None
    connector_id: str | None
    primary_entity: str | None
    fields: list[str]
    entities: list[str]
    join_type: str | None
    join_keys: list[dict[str, str]]
    snapshot_id: str | None
    row_count: int | None
    columns: list[str]


class AutoRunState(TypedDict, total=False):
    graph_run_id: str
    actor: str
    comparison_type: str
    mapping_sheet: Any
    identification: dict[str, Any]

    source: SideState
    target: SideState

    # Resolved connector query spec per side (S4: {"primary": {...}, "joins":
    # [...]}; IBP: {"entity": str, "selected": [...]}) — set once by
    # resolve_schema, reused unchanged by every batch in run_batches (no
    # re-resolution, no interrupts possible inside the batch loop).
    source_spec: dict[str, Any]
    target_spec: dict[str, Any]

    # Stage 3 (LLM ONLY): {"source": {"product": {...}, "location": {...}},
    # "target": {...}} — candidate business-identifier keys, used exclusively
    # to drive value pairing (run_batches). Never fed into business_key (see
    # compile_contract) — that stays a separate, deterministic concept. Set by
    # resolve_schema.
    candidate_keys: dict[str, Any]

    # role ("product"/"location"/"date"/"quantity") -> the actual (preview-
    # verified) column name detected for it (never a hardcoded literal) — set
    # by resolve_schema, reused by compile_contract/plan_date_batches/
    # run_batches so all three stay consistent.
    source_field_roles: dict[str, str]
    target_field_roles: dict[str, str]

    contract_id: str | None
    contract_version: int | None

    # storage.result_store result id the streaming batch loop appends to —
    # set by run_batches's first batch (or read back from
    # pipeline_run_store.get_run_batch_checkpoint on a retry).
    result_id: str | None
    batch_count: int | None

    run_id: str | None
    result_summary: dict[str, Any] | None

    status: str  # "running" | "completed" | "failed"
    failed_step: str | None
    error: str | None
    step_timestamps: dict[str, dict[str, float]]
