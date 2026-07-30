"""Graph state for the Auto-mode pipeline.

Kept as a plain TypedDict (LangGraph's native state shape) rather than a
pydantic model — nothing here needs validation beyond what each node already
enforces before writing to it.
"""

from __future__ import annotations

from typing import Any, TypedDict

STEP_NAMES = (
    "select_source",
    "import_source",
    "select_target",
    "import_target",
    "identify_candidate_keys",
    "extract_unique_keys",
    "pair_values",
    "compile_and_run",
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

    unique_values: dict[str, Any]

    # Stage 3 (LLM ONLY): {"source": {"product": {...}, "location": {...}},
    # "target": {...}} — candidate business-identifier keys, used exclusively
    # to drive value pairing (extract_unique_keys/pair_values). Never fed into
    # business_key (see compile_and_run) — that stays a separate, deterministic
    # concept. Set by identify_candidate_keys.
    candidate_keys: dict[str, Any]

    # role ("product"/"location"/"date"/"quantity") -> the actual fetched
    # column name detected for it (never a hardcoded literal) — set by
    # pair_values_step, reused by compile_and_run so both stay consistent.
    source_field_roles: dict[str, str]
    target_field_roles: dict[str, str]

    product_mapping: dict[str, Any] | None
    location_mapping: dict[str, Any] | None

    contract_id: str | None
    contract_version: int | None
    run_id: str | None
    result_summary: dict[str, Any] | None

    status: str  # "running" | "completed" | "failed"
    failed_step: str | None
    error: str | None
    step_timestamps: dict[str, dict[str, float]]
