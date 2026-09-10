"""Orchestration service — the lifecycle wiring.

    ingest snapshot (immutable)
        -> compile draft (compiler; LLM emits JSON only)
        -> validate (Gate 1 structural + Gate 2 sample replay)
        -> human approval (versioned)
        -> run reconciliation (deterministic engine, no LLM)
             Raw_Source --contract--> Shadow_Source
             Shadow_Source FULL OUTER JOIN Raw_Target -> classified results

Every step writes an audit event. This module never executes contract code —
it only orchestrates the deterministic engine and the stores.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any

import pandas as pd

logger = logging.getLogger("recon.service")

from backend.recon_engine.compiler import (
    ContractCompiler,
    ContractCompilerError,
    GroqContractCompiler,
    StubContractCompiler,
)
from backend.recon_engine import attribute_library
from backend.recon_engine.config import get_settings
from backend.recon_engine.engine import (
    LINEAGE_COL,
    build_shadow_source,
    reconcile,
    shadow_fingerprint,
)
from backend.recon_engine.models.audit import AuditAction
from backend.recon_engine.models.contract import (
    AggregationRule,
    ApprovalStatus,
    BusinessKeyField,
    CompareField,
    DraftContract,
    TransformationContract,
)
from backend.recon_engine.models.results import excluded_unmapped_counts
from backend.recon_engine.models.rules import BusinessRules, normalize_business_rules
from backend.recon_engine.models.run import ReconciliationRun, RunStatus
from backend.recon_engine.models.snapshot import RawLayer, RawSnapshot
from backend.recon_engine.models.value_mapping import ValueMapping
from backend.recon_engine.scripting import (
    ScriptApproval,
    ScriptPreview,
    TransformationScript,
    execute_script,
    generate_script,
    script_sha256,
    validate_script,
)
from backend.recon_engine.scripting.models import PreviewStatus
from backend.recon_engine.storage import (
    audit_store,
    contract_store,
    result_store,
    run_store,
    run_value_mapping_store,
    script_store,
    shadow_store,
    snapshot_store,
)
from backend.recon_engine.storage.db import init_storage
from backend.recon_engine.validation import replay_sample, validate_structural


# ── snapshots ────────────────────────────────────────────────────────────────

def ingest_snapshot(
    df: pd.DataFrame,
    *,
    layer: RawLayer,
    source_type: str,
    comparison_type: str | None = None,
    created_by: str = "system",
    lineage: dict | None = None,
) -> RawSnapshot:
    init_storage()
    snap = snapshot_store.create_snapshot(
        df,
        layer=layer,
        source_type=source_type,
        comparison_type=comparison_type,
        created_by=created_by,
        lineage=lineage,
    )
    audit_store.record(
        AuditAction.SNAPSHOT_CREATED,
        entity_type="snapshot",
        entity_id=snap.snapshot_id,
        actor=created_by,
        details={"layer": snap.layer.value, "hash": snap.snapshot_hash, "rows": snap.row_count},
    )
    return snap


# ── compile ──────────────────────────────────────────────────────────────────

def _resolve_source_name(name: str, source_schema: list[str]) -> str:
    """Resolve a UI field name to a real source column (exact, else case-insensitive).

    Falls back to the original name when nothing matches so Gate 1 surfaces a
    clear "not in source schema" error rather than silently dropping the rule.
    """
    if name in source_schema:
        return name
    lower = {c.lower(): c for c in source_schema}
    return lower.get(name.lower(), name)


def compile_draft(
    *,
    mapping_sheet: list[dict[str, Any]] | dict[str, Any],
    rules: str,
    business_rules: BusinessRules | dict[str, Any] | None = None,
    aggregation_rules: list[dict[str, Any]] | None = None,
    business_key: list[dict[str, Any]] | None = None,
    compare_fields: list[dict[str, Any]] | None = None,
    value_mappings: list[dict[str, Any]] | None = None,
    source_schema: list[str],
    target_schema: list[str],
    comparison_type: str,
    source_type: str,
    target_type: str,
    compiler: ContractCompiler | None = None,
    actor: str = "system",
) -> tuple[DraftContract, str | None]:
    """Produce a draft contract. Returns ``(draft, degraded_reason)``.

    ``business_rules`` (the structured Business Rules Builder output) is the
    preferred instruction channel. It is normalised here (whitespace trimmed,
    empty rows dropped) once, for every compiler. When it contains any rules,
    the legacy free-text ``rules`` string is ignored entirely — callers should
    stop sending both, but if they do, structured rules win. When it's empty,
    ``rules`` is used as-is, preserving the old free-text behaviour for
    callers that have not adopted the Business Rules Builder yet.

    ``business_key`` / ``compare_fields`` (the Rules step's confirmed field
    mapping) and ``value_mappings`` (the deterministic matching engine's
    output, once a human has approved it on the Mapping Review page) are never
    decided by a compiler (the LLM compiler or the stub always emit them
    empty — see ``ContractBody``'s docstring) — they are attached onto the
    draft here, deterministically, exactly like ``aggregation_rules`` below.

    When no ``compiler`` is supplied, the Azure-AI-Foundry-backed
    ``GroqContractCompiler`` (name kept for backward compatibility) is
    attempted first if configured (``AZURE_FOUNDRY_MODEL`` set) — there is no
    fallback to another provider. By
    default, any failure — connection error, bad response, invalid JSON, a
    draft that fails its own schema — degrades to the deterministic stub
    compiler instead of failing the request, mirroring the
    script-transformation generator's fallback
    (:func:`backend.recon_engine.scripting.generate_script`). Set
    ``RECON_GROQ_STRICT=true`` to instead raise the original
    :class:`ContractCompilerError` — useful in any environment where a
    stub-compiled contract silently reaching Gate 1 should be treated as a
    bug. Every attempt and outcome is logged either way; degradation is never
    silent.

    ``degraded_reason`` is ``None`` when the LLM compile succeeded, when it was
    never attempted (unconfigured — the stub is simply the normal offline
    path), or when a caller supplied an explicit ``compiler`` override (used in
    tests). An explicit ``compiler`` is used as-is and never falls back
    automatically — only the default LLM-vs-stub auto-selection degrades.
    """
    init_storage()
    degraded_reason: str | None = None
    active_compiler = compiler

    normalized_rules = normalize_business_rules(business_rules)
    effective_rules_text = rules if normalized_rules.is_empty() else ""

    if active_compiler is None and get_settings().any_llm_configured:
        groq_compiler = GroqContractCompiler()
        try:
            draft = groq_compiler.compile(
                mapping_sheet=mapping_sheet,
                rules=effective_rules_text,
                business_rules=normalized_rules,
                source_schema=source_schema,
                target_schema=target_schema,
                comparison_type=comparison_type,
                source_type=source_type,
                target_type=target_type,
            )
            active_compiler = groq_compiler
        except ContractCompilerError as exc:
            if get_settings().groq_strict:
                logger.exception(
                    "Azure AI Foundry compile failed and RECON_GROQ_STRICT is set; raising "
                    "instead of degrading to the stub compiler."
                )
                raise
            logger.exception(
                "Azure AI Foundry compile failed; degrading to StubContractCompiler. "
                "Set RECON_GROQ_STRICT=true to raise instead."
            )
            degraded_reason = f"Azure AI Foundry compile failed: {exc}"
            active_compiler = StubContractCompiler()
            draft = active_compiler.compile(
                mapping_sheet=mapping_sheet,
                rules=effective_rules_text,
                business_rules=normalized_rules,
                source_schema=source_schema,
                target_schema=target_schema,
                comparison_type=comparison_type,
                source_type=source_type,
                target_type=target_type,
            )
    else:
        active_compiler = active_compiler or StubContractCompiler()
        draft = active_compiler.compile(
            mapping_sheet=mapping_sheet,
            rules=effective_rules_text,
            business_rules=normalized_rules,
            source_schema=source_schema,
            target_schema=target_schema,
            comparison_type=comparison_type,
            source_type=source_type,
            target_type=target_type,
        )

    # Attach structured aggregation rules deterministically (schema-resolved),
    # independent of which compiler ran — this is pass-through user input, never
    # something the LLM should invent.
    resolved_aggs: list[AggregationRule] = []
    for r in aggregation_rules or []:
        sf, ag = r.get("source_field"), r.get("aggregation")
        if not sf or not ag:
            continue
        try:
            resolved_aggs.append(
                AggregationRule(source_field=_resolve_source_name(str(sf), source_schema), aggregation=ag)
            )
        except Exception:  # noqa: BLE001 - skip an unrecognised aggregation type
            logger.warning("Dropping aggregation rule with invalid type: field=%r agg=%r", sf, ag)

    # Attach the confirmed field mapping (business_key / compare_fields) and
    # any approved deterministic value mappings — human-owned inputs a
    # compiler is never allowed to decide (see ContractBody's docstring).
    # Resolved against the real source schema the same way aggregation rules
    # are, so a UI label that doesn't match the schema is dropped rather than
    # silently producing a contract Gate 1 will reject anyway.
    resolved_business_key: list[BusinessKeyField] = []
    for k in business_key or []:
        sf, tf = k.get("source_field"), k.get("target_field")
        if not sf or not tf:
            continue
        resolved_business_key.append(
            BusinessKeyField(source_field=_resolve_source_name(str(sf), source_schema), target_field=str(tf))
        )

    resolved_compare_fields: list[CompareField] = []
    for c in compare_fields or []:
        sf, tf = c.get("source_field"), c.get("target_field")
        if not sf or not tf:
            continue
        resolved_compare_fields.append(
            CompareField(
                source_field=_resolve_source_name(str(sf), source_schema),
                target_field=str(tf),
                match_type=c.get("match_type", "exact"),
                tolerance=c.get("tolerance"),
            )
        )

    resolved_value_mappings: list[ValueMapping] = []
    for vm in value_mappings or []:
        try:
            resolved_value_mappings.append(ValueMapping.model_validate(vm))
        except Exception:  # noqa: BLE001 - skip a malformed value mapping entry
            logger.warning("Dropping invalid value_mapping entry: %r", vm)

    updates: dict[str, Any] = {}
    if resolved_aggs:
        updates["aggregation_rules"] = resolved_aggs
    if resolved_business_key:
        updates["business_key"] = resolved_business_key
    if resolved_compare_fields:
        updates["compare_fields"] = resolved_compare_fields
    if resolved_value_mappings:
        updates["value_mappings"] = resolved_value_mappings
    if updates:
        draft = draft.model_copy(update=updates)

    logger.info(
        "compile_draft: using compiler=%s degraded=%s operations=%d business_key=%d "
        "compare_fields=%d aggregation_rules=%d",
        active_compiler.name, degraded_reason is not None,
        len(draft.operations), len(draft.business_key), len(draft.compare_fields),
        len(draft.aggregation_rules),
    )

    audit_store.record(
        AuditAction.CONTRACT_DRAFTED,
        entity_type="contract",
        entity_id=f"draft:{comparison_type}",
        actor=actor,
        details={
            "compiler": active_compiler.name,
            "operations": len(draft.operations),
            "degraded_reason": degraded_reason,
        },
    )
    return draft, degraded_reason


# ── validate ─────────────────────────────────────────────────────────────────

def validate_draft(
    draft: DraftContract | dict,
    *,
    source_columns: list[str],
    target_columns: list[str],
    source_sample: pd.DataFrame,
    target_sample: pd.DataFrame,
    actor: str = "system",
) -> dict[str, Any]:
    """Run both gates. Returns a report; ``ok`` is True only if both pass."""
    init_storage()
    gate1 = validate_structural(draft, source_columns, target_columns)

    if gate1.ok:
        gate2 = replay_sample(draft, source_sample, target_sample)
    else:
        # Don't replay a structurally-invalid contract.
        from backend.recon_engine.validation.gate2_replay import Gate2Report

        gate2 = Gate2Report(ok=False, errors=["skipped: gate 1 failed"])

    ok = gate1.ok and gate2.ok
    report = {"ok": ok, "gate1": gate1.as_dict(), "gate2": gate2.as_dict()}

    audit_store.record(
        AuditAction.CONTRACT_VALIDATED if ok else AuditAction.CONTRACT_VALIDATION_FAILED,
        entity_type="contract",
        entity_id="draft",
        actor=actor,
        details={"gate1_ok": gate1.ok, "gate2_ok": gate2.ok},
    )
    return report


# ── approve (human) ────────────────────────────────────────────────────────

def approve_contract(
    draft: DraftContract | dict,
    *,
    approved_by: str,
    contract_id: str | None = None,
) -> TransformationContract:
    """Promote a validated draft into a versioned, APPROVED contract.

    No automatic promotion — this must be called explicitly by the approval
    workflow after a human review. The caller is responsible for having run
    :func:`validate_draft` successfully first.
    """
    init_storage()
    if isinstance(draft, dict):
        draft = DraftContract.model_validate(draft)

    contract_id = contract_id or ("contract_" + uuid.uuid4().hex[:12])
    version = contract_store.next_version(contract_id)

    approved = TransformationContract(
        contract_id=contract_id,
        contract_version=version,
        comparison_type=draft.comparison_type,
        source_type=draft.source_type,
        target_type=draft.target_type,
        operations=draft.operations,
        aggregation_rules=draft.aggregation_rules,
        business_key=draft.business_key,
        compare_fields=draft.compare_fields,
        value_mappings=draft.value_mappings,
        source_schema=draft.source_schema,
        target_schema=draft.target_schema,
        options=draft.options,
        notes=draft.notes,
        created_by=draft.created_by,
        compiler=draft.compiler,
        approval_status=ApprovalStatus.APPROVED,
        approved_by=approved_by,
        approved_at=datetime.now(timezone.utc),
    )
    contract_store.save_contract(approved)
    audit_store.record(
        AuditAction.CONTRACT_APPROVED,
        entity_type="contract",
        entity_id=contract_id,
        actor=approved_by,
        details={"version": version},
    )
    return approved


# ── shadow preview (Review-Changes checkpoint, read-only) ────────────────────

class ShadowFingerprintMismatch(ValueError):
    """The reviewed shadow no longer matches what a run would produce.

    Raised when a run is asked to verify an ``expected_shadow_fingerprint`` that
    doesn't equal the fingerprint of the freshly rebuilt Shadow_Source — i.e.
    the contract or source snapshot changed since the user approved the review,
    so the review must be redone before reconciling.
    """


def _jsonable(value: Any) -> Any:
    """One cell -> a JSON-serialisable scalar (NaN/NaT -> None)."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


def _truncate_cell(value: Any, max_chars: int) -> Any:
    """Cap a single previewed cell's text length.

    Only strings are truncated (numbers/bools pass through unchanged). A handful
    of very long text fields — SAP long descriptions, concatenated keys, JSON
    blobs — can otherwise dominate an otherwise-small preview payload. ``0``
    disables truncation.
    """
    if max_chars and isinstance(value, str) and len(value) > max_chars:
        return value[:max_chars] + "…"
    return value


def _rows_as_records(
    df: pd.DataFrame, limit: int, *, max_chars: int | None = None
) -> list[dict[str, Any]]:
    if max_chars is None:
        max_chars = get_settings().preview_cell_chars
    head = df.head(max(0, limit))
    return [
        {str(col): _truncate_cell(_jsonable(row[col]), max_chars) for col in df.columns}
        for _, row in head.iterrows()
    ]


def _change_kind(before: Any, after: Any) -> tuple[bool, str]:
    """Classify a before/after cell into unchanged | added | removed | modified.

    Comparison is on the JSON-safe string form so "5006" vs 5006 don't read as
    a spurious change. Empty string and None are both treated as "absent".
    """
    b, a = _jsonable(before), _jsonable(after)
    b_blank = b is None or (isinstance(b, str) and b.strip() == "")
    a_blank = a is None or (isinstance(a, str) and a.strip() == "")
    if str(b) == str(a):
        return False, "unchanged"
    if b_blank and not a_blank:
        return True, "added"
    if a_blank and not b_blank:
        return True, "removed"
    return True, "modified"


def _compute_row_diffs(
    raw_source: pd.DataFrame,
    shadow_display: pd.DataFrame,
    lineage: list[list[int]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Row-level before/after diffs aligning each shadow row to its source row(s).

    Uses the executor's lineage so filters/aggregations are handled: a 1:1 row
    yields per-field before/after changes; a collapsed (aggregated) row reports
    the originating source rows and shows the derived values as its 'after'.
    """
    raw = raw_source.reset_index(drop=True)
    shadow = shadow_display.reset_index(drop=True)
    raw_cols = {str(c) for c in raw.columns}
    all_cols = list(dict.fromkeys([*map(str, raw.columns), *map(str, shadow.columns)]))
    # Truncate only the values shipped in the payload; change detection below
    # runs on the full values first, so a truncated tail can't mask a diff.
    max_chars = get_settings().preview_cell_chars

    diffs: list[dict[str, Any]] = []
    for pos in range(min(len(shadow), max(0, limit))):
        src_ids = lineage[pos] if pos < len(lineage) else []
        s_row = shadow.iloc[pos]

        if len(src_ids) == 1 and 0 <= src_ids[0] < len(raw):
            orig = raw.iloc[src_ids[0]]
            changes = []
            for col in all_cols:
                before = orig[col] if col in raw_cols else None
                after = s_row[col] if col in shadow.columns else None
                changed, kind = _change_kind(before, after)
                changes.append({
                    "field": col,
                    "before": _truncate_cell(_jsonable(before), max_chars),
                    "after": _truncate_cell(_jsonable(after), max_chars),
                    "changed": changed,
                    "kind": kind,
                })
            diffs.append({
                "row_index": pos,
                "source_row_index": int(src_ids[0]),
                "aggregated": False,
                "changes": changes,
            })
        else:
            # Filtered/aggregated: no single originating row to diff against.
            changes = [
                {
                    "field": col,
                    "before": None,
                    "after": _truncate_cell(_jsonable(s_row[col]), max_chars)
                    if col in shadow.columns
                    else None,
                    "changed": True,
                    "kind": "aggregated",
                }
                for col in all_cols
            ]
            diffs.append({
                "row_index": pos,
                "source_row_indices": [int(i) for i in src_ids],
                "aggregated": True,
                "changes": changes,
            })
    return diffs


def build_shadow_preview(
    *,
    contract_id: str,
    contract_version: int | None = None,
    source_snapshot_id: str,
    target_snapshot_id: str | None = None,
    preview_rows: int = 200,
    target_preview_rows: int = 200,
    actor: str = "system",
) -> dict[str, Any]:
    """Build (but do NOT persist as a run) the Shadow_Source for review.

    Applies the APPROVED contract's operations to the raw source snapshot to
    produce the Shadow_Source, computes row-level before/after diffs, and
    returns everything the Review-Changes screen needs — plus a
    ``shadow_fingerprint`` the subsequent run verifies. This is a pure read: no
    run, shadow, or result records are created. Because the shadow is a
    deterministic function of (approved contract + immutable source snapshot),
    rebuilding it at run time reproduces exactly what was reviewed.
    """
    init_storage()

    if contract_version is None:
        contract = contract_store.get_latest_approved(contract_id)
    else:
        contract = contract_store.get_contract(contract_id, contract_version)
    if contract is None:
        raise ValueError(f"No transformation rules found for {contract_id} v{contract_version}.")
    if not contract.is_executable():
        raise ValueError(
            f"Transformation rules {contract_id} v{contract.contract_version} are not approved yet; "
            "the preview can only be built from approved transformation rules."
        )

    raw_source = snapshot_store.load_snapshot_frame(source_snapshot_id)
    src_snap = snapshot_store.get_snapshot(source_snapshot_id)

    built = build_shadow_source(contract, raw_source)
    shadow_display = built.shadow_df.drop(columns=[LINEAGE_COL], errors="ignore")
    fingerprint = shadow_fingerprint(built.shadow_df)

    diffs = _compute_row_diffs(raw_source, shadow_display, built.lineage, limit=preview_rows)
    changed_cells = sum(
        1 for d in diffs for c in d["changes"] if c.get("changed")
    )

    target_block: dict[str, Any] | None = None
    if target_snapshot_id:
        raw_target = snapshot_store.load_snapshot_frame(target_snapshot_id)
        tgt_snap = snapshot_store.get_snapshot(target_snapshot_id)
        target_block = {
            "columns": [str(c) for c in raw_target.columns],
            "rows": _rows_as_records(raw_target, target_preview_rows),
            "total_rows": int(raw_target.shape[0]),
            "snapshot": tgt_snap.model_dump(mode="json") if tgt_snap else None,
        }

    audit_store.record(
        AuditAction.SHADOW_CREATED,
        entity_type="shadow_preview",
        entity_id=f"{contract.contract_id}:v{contract.contract_version}",
        actor=actor,
        details={
            "source_snapshot_id": source_snapshot_id,
            "fingerprint": fingerprint,
            "row_count_changed": len(shadow_display) != len(raw_source),
            "persisted": False,
        },
    )

    return {
        "contract_id": contract.contract_id,
        "contract_version": contract.contract_version,
        "operations": [op.model_dump(mode="json") for op in contract.operations],
        "aggregation_rules": [a.model_dump(mode="json") for a in contract.aggregation_rules],
        "business_key": [k.model_dump(mode="json") for k in contract.business_key],
        "compare_fields": [c.model_dump(mode="json") for c in contract.compare_fields],
        "source": {
            "columns": [str(c) for c in raw_source.columns],
            "rows": _rows_as_records(raw_source, preview_rows),
            "total_rows": int(raw_source.shape[0]),
            "snapshot": src_snap.model_dump(mode="json") if src_snap else None,
        },
        "shadow": {
            "columns": [str(c) for c in shadow_display.columns],
            "rows": _rows_as_records(shadow_display, preview_rows),
            "total_rows": int(shadow_display.shape[0]),
        },
        "target": target_block,
        "diffs": diffs,
        "shadow_fingerprint": fingerprint,
        "row_count_changed": len(shadow_display) != len(raw_source),
        "changed_cells": changed_cells,
        "preview_rows": min(preview_rows, len(shadow_display)),
    }


# ── recipe preview (draft, per-step, read-only) ──────────────────────────────

def build_recipe_preview(
    *,
    draft: dict[str, Any] | DraftContract,
    source_snapshot_id: str | None = None,
    source_rows: list[dict[str, Any]] | None = None,
    active_step_index: int | None = None,
    preview_rows: int = 100,
    actor: str = "system",
) -> dict[str, Any]:
    """Live before/after preview for the recipe editor — no approval, no run.

    Unlike :func:`build_shadow_preview` (which requires an APPROVED, persisted
    contract), this runs an UNSAVED ``draft``'s operations against a SAMPLE of
    the raw source so the editor can show the effect of each step as it is
    authored. It reuses the exact deterministic executor
    (:func:`build_shadow_source`) and the exact diff engine
    (:func:`_compute_row_diffs`) the Review-Changes checkpoint uses — there is no
    parallel preview engine, so what the user sees here is what a real run does.

    ``active_step_index`` drives the "up to this step" preview: operations AFTER
    that index (in authored order) are treated as disabled for this call, so the
    preview reflects the recipe truncated at the selected step. Each op's own
    ``enabled`` flag is still honoured. Because the executor buckets by fixed
    phase and preserves within-phase order (Decision B), the previewed prefix is
    exactly the subset a run of that prefix would execute.

    Provide the source as either a persisted ``source_snapshot_id`` (a sample is
    taken) or inline ``source_rows`` (already a sample). Raw source is never
    mutated (the executor copies).
    """
    init_storage()

    if isinstance(draft, DraftContract):
        parsed = draft
    else:
        parsed = DraftContract.model_validate(draft)

    # Resolve the source sample.
    if source_snapshot_id:
        raw_source = snapshot_store.load_snapshot_frame(source_snapshot_id).head(
            max(1, preview_rows)
        )
    elif source_rows is not None:
        raw_source = pd.DataFrame(source_rows).head(max(1, preview_rows))
    else:
        raise ValueError("Provide either source_snapshot_id or source_rows.")

    # Truncate the recipe to the enabled prefix: disable every op after the
    # selected step (authored order) without mutating the caller's draft.
    ops = list(parsed.operations)
    if active_step_index is not None:
        ops = [
            op.model_copy(update={"enabled": op.enabled and i <= active_step_index})
            for i, op in enumerate(ops)
        ]
        parsed = parsed.model_copy(update={"operations": ops})

    built = build_shadow_source(parsed, raw_source)
    shadow_display = built.shadow_df.drop(columns=[LINEAGE_COL], errors="ignore")
    fingerprint = shadow_fingerprint(built.shadow_df)

    diffs = _compute_row_diffs(raw_source, shadow_display, built.lineage, limit=preview_rows)
    changed_cells = sum(1 for d in diffs for c in d["changes"] if c.get("changed"))
    # Columns touched anywhere in the sample — drives the editor's affected-column
    # highlight without the UI having to re-scan every cell.
    affected_columns = sorted(
        {
            c["field"]
            for d in diffs
            for c in d["changes"]
            if c.get("changed") and c.get("field")
        }
    )

    return {
        "operations": [op.model_dump(mode="json") for op in parsed.operations],
        "active_step_index": active_step_index,
        "source": {
            "columns": [str(c) for c in raw_source.columns],
            "rows": _rows_as_records(raw_source, preview_rows),
            "total_rows": int(raw_source.shape[0]),
        },
        "shadow": {
            "columns": [str(c) for c in shadow_display.columns],
            "rows": _rows_as_records(shadow_display, preview_rows),
            "total_rows": int(shadow_display.shape[0]),
        },
        "diffs": diffs,
        "affected_columns": affected_columns,
        "changed_cells": changed_cells,
        "row_count_changed": len(shadow_display) != len(raw_source),
        "shadow_fingerprint": fingerprint,
        "preview_rows": min(preview_rows, len(shadow_display)),
    }


# ── run reconciliation (runtime, deterministic) ─────────────────────────────

def _store_back_attribute_library(contract, run_id: str, summary, actor: str) -> None:
    """Upsert a completed run's field mapping into the library (never raises).

    Confidence is the run's match rate — a cheap, honest signal the LLM output
    doesn't carry — so the Library tab can rank/annotate stored mappings.
    """
    try:
        total = getattr(summary, "total", 0) or 0
        confidence = (summary.match / total) if total else None
        attribute_library.store_back_from_contract(
            contract, run_id, confidence=confidence, actor=actor
        )
    except Exception:  # noqa: BLE001 — store-back is best-effort, never fatal
        logger.warning(
            "Attribute-library store-back failed for run %s", run_id, exc_info=True
        )


def run_reconciliation(
    *,
    contract_id: str,
    contract_version: int | None = None,
    source_snapshot_id: str,
    target_snapshot_id: str,
    expected_shadow_fingerprint: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Execute an APPROVED contract. Builds a Shadow_Source, reconciles it
    against Raw_Target, persists results, and returns run + result ids.

    When ``expected_shadow_fingerprint`` is supplied (the Review-Changes
    checkpoint passes the fingerprint the user approved), the freshly built
    Shadow_Source is verified against it BEFORE reconciling. A mismatch raises
    :class:`ShadowFingerprintMismatch` — the contract or source snapshot changed
    since review, so the review must be redone. Omitting it preserves the
    original unguarded behaviour (e.g. direct API callers, tests)."""
    init_storage()

    if contract_version is None:
        contract = contract_store.get_latest_approved(contract_id)
    else:
        contract = contract_store.get_contract(contract_id, contract_version)

    if contract is None:
        raise ValueError(f"No transformation rules found for {contract_id} v{contract_version}.")
    if not contract.is_executable():
        raise ValueError(
            f"Transformation rules {contract_id} v{contract.contract_version} are not approved yet; "
            "only approved transformation rules can be run."
        )

    run = ReconciliationRun(
        run_id=run_store.new_run_id(),
        contract_id=contract.contract_id,
        contract_version=contract.contract_version,
        source_snapshot_id=source_snapshot_id,
        target_snapshot_id=target_snapshot_id,
        status=RunStatus.RUNNING,
        created_by=actor,
    )
    run_store.save_run(run)
    audit_store.record(
        AuditAction.RUN_STARTED, entity_type="run", entity_id=run.run_id, actor=actor,
        details={"contract_id": contract.contract_id, "version": contract.contract_version},
    )

    try:
        raw_source = snapshot_store.load_snapshot_frame(source_snapshot_id)
        raw_target = snapshot_store.load_snapshot_frame(target_snapshot_id)
        src_snap = snapshot_store.get_snapshot(source_snapshot_id)

        built = build_shadow_source(contract, raw_source)

        # Review-Changes guard: the shadow we're about to reconcile must be the
        # exact one the user approved. A deterministic rebuild from the same
        # (approved contract + immutable snapshot) reproduces it; a mismatch
        # means something changed since review and it must be redone.
        if expected_shadow_fingerprint is not None:
            actual = shadow_fingerprint(built.shadow_df)
            if actual != expected_shadow_fingerprint:
                raise ShadowFingerprintMismatch(
                    "The shadow dataset changed since it was reviewed "
                    f"(reviewed={expected_shadow_fingerprint[:12]}…, "
                    f"now={actual[:12]}…). Re-run the Review Changes step before reconciling."
                )

        shadow = shadow_store.create_shadow(
            built.shadow_df,
            run_id=run.run_id,
            contract_id=contract.contract_id,
            contract_version=contract.contract_version,
            raw_snapshot_id=source_snapshot_id,
            raw_snapshot_hash=src_snap.snapshot_hash if src_snap else "",
        )
        run.shadow_id = shadow.shadow_id
        run_store.update_run(run)
        audit_store.record(
            AuditAction.SHADOW_CREATED, entity_type="shadow", entity_id=shadow.shadow_id,
            actor=actor, details={"run_id": run.run_id, "expires_at": shadow.expires_at.isoformat()},
        )

        recon = reconcile(contract, built.shadow_df, raw_target)
        recon.summary.excluded_unmapped = excluded_unmapped_counts(built.held_out)
        recon.detail_df = attach_field_values(
            recon.detail_df, contract, shadow_df=built.shadow_df, target_df=raw_target, raw_source_df=raw_source,
        )
        result = result_store.save_result(
            run_id=run.run_id,
            contract_id=contract.contract_id,
            contract_version=contract.contract_version,
            summary=recon.summary,
            detail_df=recon.detail_df,
        )

        run.status = RunStatus.COMPLETED
        run_store.update_run(run)
        audit_store.record(
            AuditAction.RUN_COMPLETED, entity_type="run", entity_id=run.run_id, actor=actor,
            details={"result_id": result.result_id, "summary": recon.summary.model_dump()},
        )
        # Store-back: this contract's FIELD mapping drove a COMPLETED run, so
        # upsert it into the attribute-mapping library keyed by the canonical
        # column-set key. Wrapped so a store failure can never break a run that
        # already succeeded.
        _store_back_attribute_library(contract, run.run_id, recon.summary, actor)
        return {
            "run_id": run.run_id,
            "shadow_id": shadow.shadow_id,
            "result_id": result.result_id,
            "summary": recon.summary.model_dump(),
        }
    except Exception as exc:  # noqa: BLE001 - record failure then re-raise
        run.status = RunStatus.FAILED
        run.error = str(exc)
        run_store.update_run(run)
        audit_store.record(
            AuditAction.RUN_FAILED, entity_type="run", entity_id=run.run_id, actor=actor,
            details={"error": str(exc)},
        )
        raise


# ── script-transformation flow (Transformation Preview → User Approval) ─────
#
# Feature-flagged alternative to the contract flow (USE_SCRIPT_TRANSFORMATIONS).
# The user approves transformed DATA, never code; the approval pins the exact
# script hash, and production execution refuses anything else. Reconciliation
# itself is untouched — it still consumes Shadow_Source vs Raw_Target.

def generate_transformation_script(
    *,
    parsed_mapping: dict[str, Any] | list[dict[str, Any]],
    rules: str,
    business_rules: BusinessRules | dict[str, Any] | None = None,
    source_schema: list[str],
    target_schema: list[str],
    actor: str = "system",
) -> tuple[TransformationScript, dict[str, Any], str | None]:
    """Generate + statically validate + persist a transformation script.

    ``business_rules`` (structured Business Rules Builder output) takes
    precedence over the legacy free-text ``rules`` string when non-empty,
    same precedence as the contract compiler (:func:`compile_draft`). The
    script generator's prompt only understands a single free-text rules
    string, so structured rules are rendered to text
    (:meth:`BusinessRules.to_prompt_text`) before being passed through.

    Returns ``(script, validation_report, degraded_reason)``. Groq failures
    degrade to the deterministic fallback generator — never an error."""
    init_storage()
    normalized_rules = normalize_business_rules(business_rules)
    effective_rules = rules if normalized_rules.is_empty() else normalized_rules.to_prompt_text()
    script, degraded_reason = generate_script(
        parsed_mapping=parsed_mapping,
        rules=effective_rules,
        source_schema=source_schema,
        target_schema=target_schema,
        actor=actor,
    )
    report = validate_script(script.script).as_dict()
    script_store.save_script(script, validation=report)
    audit_store.record(
        AuditAction.SCRIPT_GENERATED if report["ok"] else AuditAction.SCRIPT_REJECTED,
        entity_type="script",
        entity_id=script.script_id,
        actor=actor,
        details={
            "generated_by": script.generated_by.value,
            "script_hash": script.script_hash,
            "validation_ok": report["ok"],
            "degraded_reason": degraded_reason,
        },
    )
    return script, report, degraded_reason


def preview_transformation(
    script_id: str,
    df: pd.DataFrame,
    *,
    actor: str = "system",
) -> tuple[ScriptPreview, TransformationScript]:
    """Sandbox-execute a stored script against sample data; store the snapshot."""
    init_storage()
    script = script_store.get_script(script_id)
    if script is None:
        raise KeyError(f"Unknown script '{script_id}'.")

    result = execute_script(script.script, df)
    preview = script_store.create_preview(
        result.transformed_df,
        script=script,
        affected_rows=result.affected_rows,
        modified_columns=result.modified_columns,
        row_diffs=result.row_diffs,
        execution_log=result.execution_log,
        created_by=actor,
    )
    audit_store.record(
        AuditAction.PREVIEW_CREATED,
        entity_type="preview",
        entity_id=preview.preview_id,
        actor=actor,
        details={
            "script_id": script.script_id,
            "script_hash": script.script_hash,
            "rows": preview.row_count,
            "affected_rows": preview.affected_rows,
        },
    )
    return preview, script


def approve_transformation_preview(
    preview_id: str, *, approved_by: str
) -> ScriptApproval:
    """User sign-off on the transformed data. Pins the producing script's hash."""
    init_storage()
    preview = script_store.get_preview(preview_id)
    if preview is None:
        raise KeyError(f"Unknown preview '{preview_id}'.")
    if preview.status == PreviewStatus.REJECTED:
        raise ValueError("This preview was rejected; generate a new preview to approve.")

    approval = ScriptApproval(
        approval_id="approval_" + uuid.uuid4().hex[:12],
        preview_snapshot_id=preview.preview_id,
        script_id=preview.script_id,
        script_hash=preview.script_hash,
        approved_by=approved_by,
    )
    script_store.save_approval(approval)
    script_store.set_preview_status(preview_id, PreviewStatus.APPROVED)
    audit_store.record(
        AuditAction.PREVIEW_APPROVED,
        entity_type="preview",
        entity_id=preview_id,
        actor=approved_by,
        details={"approval_id": approval.approval_id, "script_hash": approval.script_hash},
    )
    return approval


def reject_transformation_preview(
    preview_id: str, *, actor: str, reason: str | None = None
) -> None:
    init_storage()
    preview = script_store.get_preview(preview_id)
    if preview is None:
        raise KeyError(f"Unknown preview '{preview_id}'.")
    script_store.set_preview_status(preview_id, PreviewStatus.REJECTED)
    audit_store.record(
        AuditAction.PREVIEW_REJECTED,
        entity_type="preview",
        entity_id=preview_id,
        actor=actor,
        details={"script_id": preview.script_id, "reason": reason},
    )


def _resolve_shadow_field(field: str, mapped: str, shadow_columns: list[str]) -> str:
    """Source-side fields may have been renamed by the script (source name →
    target name). Resolve against what actually exists in the shadow frame."""
    if field in shadow_columns:
        return field
    if mapped in shadow_columns:
        return mapped
    return field  # let the reconciler surface the exception


def run_reconciliation_with_script(
    *,
    approval_id: str,
    source_snapshot_id: str,
    target_snapshot_id: str,
    business_key: list[dict[str, str]],
    compare_fields: list[dict[str, Any]] | None = None,
    options: dict[str, Any] | None = None,
    comparison_type: str = "custom",
    source_type: str = "excel",
    target_type: str = "excel",
    actor: str = "system",
) -> dict[str, Any]:
    """Production execution: approved (hash-pinned) script → Shadow_Source →
    the unchanged deterministic reconciler.

    The exact script that generated the approved preview is re-validated
    statically, its hash is verified against the approval, and only then is it
    executed against the full Raw_Source snapshot.
    """
    init_storage()

    approval = script_store.get_approval(approval_id)
    if approval is None:
        raise ValueError(f"No approval found for '{approval_id}'.")
    script = script_store.get_script(approval.script_id)
    if script is None:
        raise ValueError(f"Approved script '{approval.script_id}' not found.")
    if script_sha256(script.script) != approval.script_hash:
        raise ValueError(
            "Script hash mismatch: the stored script is not the one that produced "
            "the approved preview. Refusing to execute."
        )
    if not business_key:
        raise ValueError("At least one business-key field pair is required.")

    # Reconciliation config carrier — the reconciler is driven by a contract
    # object; the script flow synthesises one with NO operations (the script
    # already built the shadow) purely for keys/compare fields/options.
    synthetic_contract_id = f"script:{script.script_id}"

    run = ReconciliationRun(
        run_id=run_store.new_run_id(),
        contract_id=synthetic_contract_id,
        contract_version=1,
        source_snapshot_id=source_snapshot_id,
        target_snapshot_id=target_snapshot_id,
        status=RunStatus.RUNNING,
        created_by=actor,
    )
    run_store.save_run(run)
    audit_store.record(
        AuditAction.RUN_STARTED, entity_type="run", entity_id=run.run_id, actor=actor,
        details={
            "mode": "script",
            "approval_id": approval.approval_id,
            "script_id": script.script_id,
            "script_hash": approval.script_hash,
        },
    )

    try:
        raw_source = snapshot_store.load_snapshot_frame(source_snapshot_id)
        raw_target = snapshot_store.load_snapshot_frame(target_snapshot_id)
        src_snap = snapshot_store.get_snapshot(source_snapshot_id)

        # Full transformation: re-validates statically and runs in the same
        # restricted sandbox namespace as the preview.
        sandbox_result = execute_script(script.script, raw_source)
        shadow_df = sandbox_result.transformed_df

        shadow = shadow_store.create_shadow(
            shadow_df,
            run_id=run.run_id,
            contract_id=synthetic_contract_id,
            contract_version=1,
            raw_snapshot_id=source_snapshot_id,
            raw_snapshot_hash=src_snap.snapshot_hash if src_snap else "",
        )
        run.shadow_id = shadow.shadow_id
        run_store.update_run(run)
        audit_store.record(
            AuditAction.SHADOW_CREATED, entity_type="shadow", entity_id=shadow.shadow_id,
            actor=actor, details={"run_id": run.run_id, "mode": "script"},
        )

        shadow_columns = [str(c) for c in shadow_df.columns]
        contract = TransformationContract(
            contract_id=synthetic_contract_id,
            contract_version=1,
            comparison_type=comparison_type,
            source_type=source_type,
            target_type=target_type,
            operations=[],
            business_key=[
                {
                    "source_field": _resolve_shadow_field(
                        str(k["source_field"]), str(k["target_field"]), shadow_columns
                    ),
                    "target_field": str(k["target_field"]),
                }
                for k in business_key
            ],
            compare_fields=[
                {
                    "source_field": _resolve_shadow_field(
                        str(c["source_field"]), str(c["target_field"]), shadow_columns
                    ),
                    "target_field": str(c["target_field"]),
                    "match_type": c.get("match_type", "exact"),
                    "tolerance": c.get("tolerance"),
                }
                for c in (compare_fields or [])
            ],
            source_schema=shadow_columns,
            target_schema=[str(c) for c in raw_target.columns],
            options=options or {"case_insensitive": True, "trim_whitespace": True},
            compiler=f"script:{script.generated_by.value}",
            approval_status=ApprovalStatus.APPROVED,
            approved_by=approval.approved_by,
            approved_at=approval.approved_at,
        )

        recon = reconcile(contract, shadow_df, raw_target)
        result = result_store.save_result(
            run_id=run.run_id,
            contract_id=synthetic_contract_id,
            contract_version=1,
            summary=recon.summary,
            detail_df=recon.detail_df,
        )

        run.status = RunStatus.COMPLETED
        run_store.update_run(run)
        audit_store.record(
            AuditAction.RUN_COMPLETED, entity_type="run", entity_id=run.run_id, actor=actor,
            details={
                "result_id": result.result_id,
                "mode": "script",
                "summary": recon.summary.model_dump(),
            },
        )
        # Store-back (script flow). NB: this synthetic contract's source_schema
        # is the post-transform shadow columns, so its canonical key matches a
        # lookup only when the shadow columns equal the raw dataset columns; the
        # deterministic contract flow above is the reliable reuse path.
        _store_back_attribute_library(contract, run.run_id, recon.summary, actor)
        return {
            "run_id": run.run_id,
            "shadow_id": shadow.shadow_id,
            "result_id": result.result_id,
            "summary": recon.summary.model_dump(),
            "transformation": {
                "script_id": script.script_id,
                "script_hash": approval.script_hash,
                "generated_by": script.generated_by.value,
                "approval_id": approval.approval_id,
                "approved_by": approval.approved_by,
                "modified_columns": sandbox_result.modified_columns,
                "affected_rows": sandbox_result.affected_rows,
            },
        }
    except Exception as exc:  # noqa: BLE001 - record failure then re-raise
        run.status = RunStatus.FAILED
        run.error = str(exc)
        run_store.update_run(run)
        audit_store.record(
            AuditAction.RUN_FAILED, entity_type="run", entity_id=run.run_id, actor=actor,
            details={"error": str(exc), "mode": "script"},
        )
        raise


# ── comparison sheet export (read-only) ──────────────────────────────────────

# Business-friendly labels for the four per-record classifications. The two
# one-sided join outcomes (business key present on only one side) both
# collapse onto the same "Mismatch" category — only three categories are ever
# shown to a user: Match, Quantity Mismatch, Mismatch.
_CLASS_LABELS: dict[str, str] = {
    "match": "Match",
    "mismatch": "Quantity Mismatch",
    "missing_in_source": "Mismatch",
    "missing_in_target": "Mismatch",
}
_CLASS_REMARKS: dict[str, str] = {
    "match": "Values match within tolerance.",
    "mismatch": "Compared values differ.",
    "missing_in_source": "Business key present in target only.",
    "missing_in_target": "Business key present in source only.",
}
_CLASS_ORDER = ["match", "mismatch", "missing_in_source", "missing_in_target"]

# ── Export presentation: Status label + row fill per classification ──────────
# The export maps each per-record classification onto its own user-facing
# status and colour-codes each row (and the Summary legend) by status.
_STATUS_BY_CLASS: dict[str, str] = {
    "match": "MATCH",
    "mismatch": "QUANTITY MISMATCH",
    "missing_in_target": "MISSING IN TARGET",
    "missing_in_source": "EXTRA IN TARGET",
}
_STATUS_FILL: dict[str, str] = {
    "MATCH": "C6EFCE",           # green
    "QUANTITY MISMATCH": "FFEB9C",  # amber
    "MISSING IN TARGET": "FFC7CE",  # red
    "EXTRA IN TARGET": "BDD7EE",  # blue
}
# Summary "Results" block (task spec): one row per ReconciliationSummary field,
# matches first, then issues.
_SUMMARY_ORDER = ["match", "quantity_mismatch", "missing_in_target", "extra_in_target"]
# Summary field -> (display label, status key, per-record classifications it rolls up).
_SUMMARY_BUCKETS: dict[str, tuple[str, str, list[str]]] = {
    "match": ("Match", "MATCH", ["match"]),
    "quantity_mismatch": ("Quantity Mismatch", "QUANTITY MISMATCH", ["mismatch"]),
    "missing_in_target": ("Missing in Target", "MISSING IN TARGET", ["missing_in_target"]),
    "extra_in_target": ("Extra in Target", "EXTRA IN TARGET", ["missing_in_source"]),
}
# "All Records" sheet sort order (task spec): issues first, matches last.
_ALL_RECORDS_ORDER = ["quantity_mismatch", "missing_in_target", "extra_in_target", "match"]
_HEADER_FILL = "1F4E78"  # dark blue for the All Records header row

_FieldPair = tuple[str, str]


def _business_key_export_specs(contract: Any) -> list[tuple[str, str, Any | None]]:
    """``(source_field, target_field, value_mapping_or_None)`` per
    ``contract.business_key``, in contract order.

    Every key pair is exported as a Source + Target column pair; whether it
    "went through value-pairing" only changes what the Source column holds
    (the raw pre-mapping value, resolved via lineage, for a value-mapped key;
    the row's own value for a plain key — typically the date key) and whether
    a trailing Pair ID column is added. This is decided STRUCTURALLY: does
    ``contract.value_mappings`` have an entry for this pair's target field
    (see :func:`_find_value_mapping`, which itself matches by target-field
    name, not a literal string like ``"PRDID"``)? This also means a date key
    needs no special-casing at all — it simply has no value mapping. Works
    for any number of key pairs, not just two.
    """
    if contract is None:
        return []
    return [
        (k.source_field, k.target_field, _find_value_mapping(contract, k.target_field))
        for k in contract.business_key
    ]


def _compare_field_export_specs(contract: Any) -> list[tuple[str, str]]:
    """``(source_field, target_field)`` per ``contract.compare_fields``, in
    contract order — any number, not just one."""
    if contract is None:
        return []
    return [(c.source_field, c.target_field) for c in contract.compare_fields]


def _delta_column_name(source_field: str, target_field: str, compare_specs: list[_FieldPair]) -> str:
    """"Delta" when there's exactly one compare field (today's common case,
    kept unlabeled for brevity); otherwise disambiguated per pair so a 2nd+
    compare field's delta isn't shadowed by the first."""
    if len(compare_specs) == 1:
        return "Delta"
    return f"{source_field} → {target_field} Delta"


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    """The value of the first key that's actually IN ``mapping`` (not merely
    falsy) — lets a persisted ``field_values`` dict from an older export
    naming scheme still resolve to its real value (including a genuine
    blank), rather than always falling through past a present-but-None key."""
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _key_header_names(source_field: str, target_field: str) -> tuple[str, str]:
    """The two export column headers for one business-key pair — the actual
    source/target field names from the contract, data-driven rather than a
    generic hardcoded label. The one exception: when a plain (non-value-mapped)
    key's source and target field share the same name (typically the date
    key), a bare name would produce two identically-headed columns holding
    DIFFERENT values (the row is keyed by name internally, so the second
    write would silently clobber the first) — ``" (Source)"``/``" (Target)"``
    is added only in that specific collision case, never otherwise."""
    if source_field == target_field:
        return f"{source_field} (Source)", f"{target_field} (Target)"
    return source_field, target_field


def _export_columns_for_contract(contract: Any) -> list[str]:
    """The "All Records" sheet's column order for this contract: a Source +
    Target column per business-key pair (every key pair, value-mapped or
    plain — e.g. the date key — gets both sides so a reader can see exactly
    which side is blank on a one-sided record; header text is the contract's
    own field names, see :func:`_key_header_names`), a Pair ID immediately
    after any value-mapped key's pair (see ``recon_engine.ids``; blank for
    Manual-mode runs, which have no per-row pair identity to report), then
    "Status", then per compare field its raw source column, raw target
    column, and a Delta column (always non-negative — see :func:`_delta`) —
    always LAST, after every key column, so the comparison fields stay in a
    fixed trailing position regardless of how many key pairs the contract
    has. Computed fresh per run instead of a fixed list, so it scales to
    however many key/compare pairs the contract actually has.
    """
    key_specs = _business_key_export_specs(contract)
    compare_specs = _compare_field_export_specs(contract)
    columns: list[str] = []
    for sf, tf, vm in key_specs:
        source_header, target_header = _key_header_names(sf, tf)
        columns.append(source_header)
        columns.append(target_header)
        if vm is not None:
            columns.append(f"{sf} Pair ID")
    columns.append("Status")
    for sf, tf in compare_specs:
        columns.append(sf)
        columns.append(tf)
        columns.append(_delta_column_name(sf, tf, compare_specs))
    return columns


def _to_number(value: Any) -> float | None:
    """Best-effort numeric coercion for the Delta calculation.

    Missing/non-numeric values become ``None`` — never a silent 0, which would
    corrupt the Delta convention for the one-sided Missing/Extra cases.
    """
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _signed_delta(source_value: Any, target_value: Any) -> float | None:
    """``source_value - target_value``, signed, for one compare field's row.

    Kept signed here because Insights' netDelta (facts.py's
    ``_break_rate_summary``) sums this across every row to show whether
    source is running net-higher or net-lower than target overall — that
    cancellation needs the sign. The "All Records" sheet's own Delta column
    instead shows ``abs()`` of this value at render time (see
    ``build_comparison_workbook``), since a mismatch's size there should read
    the same regardless of which side is larger.

    Convention for the one-sided Missing/Extra cases (the app's five
    reconciliation record classes, none of which will ever populate both
    sides for those statuses): the absent side is treated as 0 — a
    Missing-in-Target row (source only) gets ``Delta = source_value``, an
    Extra-in-Target row (target only) gets ``Delta = -target_value``.
    ``None`` only when BOTH sides are absent.
    """
    src = _to_number(source_value)
    tgt = _to_number(target_value)
    if src is None and tgt is None:
        return None
    return (src or 0.0) - (tgt or 0.0)


def _index_by_key(df: pd.DataFrame | None, fields: list[str], options: dict[str, Any]) -> dict[str, pd.Series]:
    """``business_key -> row`` for a frame, using the same normalisation as
    :func:`engine.reconciler.reconcile`. Shared by :func:`attach_field_values`
    (fresh in-memory frames, right after reconciliation) and
    :func:`build_enriched_detail`'s legacy fallback (frames re-loaded from
    storage, which may be missing/expired)."""
    from backend.recon_engine.engine.reconciler import _build_key

    by_key: dict[str, pd.Series] = {}
    if df is None or df.empty:
        return by_key
    for k, (_, row) in zip(_build_key(df, fields, options), df.iterrows()):
        by_key.setdefault(k, row)
    return by_key


def _vals(row: pd.Series | None, fields: list[str]) -> str:
    if row is None:
        return ""
    return "; ".join(f"{f}={_jsonable(row[f])}" for f in fields if f in row.index)


def _side_value(row: pd.Series | None, field: str) -> Any:
    """Raw value for ``field`` off one side's row, or ``None`` when that side
    has no row at all (a one-sided Missing-in-Target/Extra-in-Target record)
    — left blank rather than borrowed from the other side, since the Source
    and Target export columns are now shown separately."""
    if row is not None and field in row.index:
        return _jsonable(row[field])
    return None


def _original_raw_value(s_row: pd.Series | None, field: str | None, raw_source_df: pd.DataFrame | None) -> Any:
    """The pre-value-mapping raw source value for ``field``, resolved via the
    shadow row's lineage back to Raw_Source. The shadow's own column already
    holds the POST-mapping (target-paired) value, so this must go back to the
    raw frame rather than reading the shadow row directly."""
    if s_row is None or field is None or raw_source_df is None:
        return None
    if LINEAGE_COL not in s_row.index:
        return None
    try:
        row_ids = json.loads(s_row[LINEAGE_COL] or "[]")
    except (TypeError, ValueError):
        return None
    if not row_ids:
        return None
    row_id = row_ids[0]
    if not (0 <= row_id < len(raw_source_df)) or field not in raw_source_df.columns:
        return None
    return _jsonable(raw_source_df.iloc[row_id][field])


def attach_field_values(
    detail_df: pd.DataFrame,
    contract: Any,
    *,
    shadow_df: pd.DataFrame,
    target_df: pd.DataFrame,
    raw_source_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Stamp every detail row with the actual field values that produced it,
    computed HERE while ``shadow_df``/``target_df``/``raw_source_df`` are
    still live in-memory frames from this reconciliation — not reconstructed
    later from a ``shadow_id``/``snapshot_id`` that may have expired (Manual
    mode's shadow TTL) or never existed as one whole-dataset frame at all
    (Auto mode's per-batch streaming extracts; see
    ``auto_pipeline.nodes._do_finalize``). Called right after
    :func:`engine.reconciler.reconcile` at every call site (Manual mode's
    ``run_reconciliation`` and Auto mode's ``auto_pipeline.nodes.
    _do_run_batches``), so the results pipeline is identical for every mode —
    only the later delivery of the export differs.

    Adds one new column, ``field_values`` — a plain per-row dict keyed
    exactly like :func:`_export_columns_for_contract`'s column names (plus
    ``source_values``/``target_values``, the same joined ``field=value``
    strings :func:`build_enriched_detail` used to compute from a live re-join)
    — same JSON-able-column convention as the existing ``field_diffs``/
    ``pair_ids`` columns. Every other column is left untouched. A no-op on an
    empty frame or a run with no contract.
    """
    if detail_df.empty or contract is None:
        return detail_df

    options = contract.options or {}
    bk_src = [k.source_field for k in contract.business_key]
    bk_tgt = [k.target_field for k in contract.business_key]
    cf_src = [c.source_field for c in contract.compare_fields]
    cf_tgt = [c.target_field for c in contract.compare_fields]
    key_specs = _business_key_export_specs(contract)
    compare_specs = _compare_field_export_specs(contract)

    shadow_by_key = _index_by_key(shadow_df, bk_src, options)
    target_by_key = _index_by_key(target_df, bk_tgt, options)

    values_col: list[dict[str, Any]] = []
    for key in detail_df["business_key"]:
        s_row = shadow_by_key.get(key)
        t_row = target_by_key.get(key)
        rec: dict[str, Any] = {
            "source_values": _vals(s_row, [*bk_src, *cf_src]),
            "target_values": _vals(t_row, [*bk_tgt, *cf_tgt]),
        }
        for sf, tf, vm in key_specs:
            source_header, target_header = _key_header_names(sf, tf)
            if vm is not None:
                rec[source_header] = _original_raw_value(s_row, sf, raw_source_df)
            else:
                rec[source_header] = _side_value(s_row, sf)
            rec[target_header] = _side_value(t_row, tf)
        for sf, tf in compare_specs:
            source_val = s_row[sf] if s_row is not None and sf in s_row.index else None
            target_val = t_row[tf] if t_row is not None and tf in t_row.index else None
            rec[sf] = _jsonable(source_val)
            rec[tf] = _jsonable(target_val)
            rec[_delta_column_name(sf, tf, compare_specs)] = _signed_delta(source_val, target_val)
        values_col.append(rec)

    out = detail_df.copy()
    out["field_values"] = values_col
    return out


def _effective_contract(contract: Any, run_id: str) -> Any:
    """The contract whose ``value_mappings`` actually produced this run's
    field values. Manual-mode runs execute the stored contract's own
    ``value_mappings`` directly, so an empty per-run accumulator (nothing
    ever recorded for this ``run_id``) falls back to it unchanged. Auto-mode
    runs resolve product/location pairing independently per date-batch into a
    throwaway per-batch contract copy (see ``auto_pipeline.nodes.
    _do_run_batches``) that is never written back to ``contract_store`` —
    the run-scoped union of every batch's resolved matches (see
    ``storage.run_value_mapping_store``) stands in for it here.
    """
    if contract is None:
        return None
    run_mappings = run_value_mapping_store.get_run_mappings(run_id)
    if not run_mappings:
        return contract
    return contract.model_copy(update={"value_mappings": run_mappings})


def build_enriched_detail(run_id: str) -> pd.DataFrame:
    """Reconstruct a run's detail rows enriched with source/target field values.

    Prefers each row's ``field_values`` column, persisted at reconciliation
    time by :func:`attach_field_values` (current pipeline, every mode).
    Falls back to re-joining the persisted Shadow_Source and Raw_Target on
    the (already-computed) business key ONLY for rows that predate that
    column (older Manual-mode runs) — that re-join is fragile (the shadow
    may have expired; Auto-mode runs have no whole-dataset shadow/snapshot
    to re-join at all, see ``auto_pipeline.nodes._do_finalize``), which is
    exactly why it is no longer the primary path.

    Per row the frame carries: ``business_key``, ``classification`` (raw enum
    value), ``classification_label`` / ``remark`` (business-friendly),
    ``detail``, ``field_diffs`` (list), ``source_values`` / ``target_values``
    (joined ``field=value`` strings), plus a column set computed per contract
    (see :func:`_export_columns_for_contract`) — a Source + Target column per
    business-key pair (for a value-mapped key, Source is the RAW
    pre-value-mapping value resolved via the shadow row's lineage back to
    Raw_Source; either side is blank when that side has no row for this
    record), ``Status``, and per compare field its raw source value, raw
    target value, and a signed Delta (see :func:`_signed_delta`). Scales to
    however many key/compare pairs the contract has — not fixed to two keys
    and one compare field.
    """
    init_storage()
    run = run_store.get_run(run_id)
    if run is None:
        raise KeyError(f"Unknown run '{run_id}'.")
    result = result_store.get_result_for_run(run_id)
    if result is None:
        raise KeyError(f"No reconciliation result found for run '{run_id}'.")

    contract = contract_store.get_contract(run.contract_id, run.contract_version)
    contract = _effective_contract(contract, run_id)
    options = (contract.options if contract else {}) or {}
    bk_src = [k.source_field for k in contract.business_key] if contract else []
    bk_tgt = [k.target_field for k in contract.business_key] if contract else []
    cf_src = [c.source_field for c in contract.compare_fields] if contract else []
    cf_tgt = [c.target_field for c in contract.compare_fields] if contract else []
    key_specs = _business_key_export_specs(contract)
    compare_specs = _compare_field_export_specs(contract)

    detail = result_store.load_result_frame_any(result.result_id)
    has_field_diffs = "field_diffs" in detail.columns
    has_pair_ids = "pair_ids" in detail.columns
    has_field_values = "field_values" in detail.columns

    # Legacy fallback lookups — only built (and only ever consulted) for rows
    # missing the eagerly-persisted ``field_values`` column; see the
    # docstring above.
    needs_legacy_join = not has_field_values or bool(
        detail["field_values"].apply(lambda v: not isinstance(v, dict) or not v).any()
    )
    shadow_by_key: dict[str, pd.Series] = {}
    target_by_key: dict[str, pd.Series] = {}
    raw_source_df: pd.DataFrame | None = None
    if needs_legacy_join:
        try:
            if run.shadow_id:
                shadow = shadow_store.load_shadow_frame(run.shadow_id)
                shadow_by_key = _index_by_key(shadow, bk_src, options)
        except Exception:  # noqa: BLE001 - expired/missing shadow is non-fatal
            logger.warning("Enriched detail: shadow frame unavailable for run %s", run_id)
        try:
            target = snapshot_store.load_snapshot_frame(run.target_snapshot_id)
            target_by_key = _index_by_key(target, bk_tgt, options)
        except Exception:  # noqa: BLE001
            logger.warning("Enriched detail: target frame unavailable for run %s", run_id)
        try:
            raw_source_df = snapshot_store.load_snapshot_frame(run.source_snapshot_id)
        except Exception:  # noqa: BLE001 - non-fatal; original-value columns are then blank
            logger.warning("Enriched detail: raw source frame unavailable for run %s", run_id)

    def _legacy_vals(row: pd.Series | None, fields: list[str]) -> str:
        if row is None:
            return ""
        return "; ".join(f"{f}={_jsonable(row[f])}" for f in fields if f in row.index)

    rows: list[dict[str, Any]] = []
    for _, d in detail.iterrows():
        key = d.get("business_key")
        cls = str(d.get("classification"))
        diffs = d["field_diffs"] if has_field_diffs else []
        if not isinstance(diffs, list):
            diffs = []
        pair_ids = d["pair_ids"] if has_pair_ids else {}
        if not isinstance(pair_ids, dict):
            pair_ids = {}
        persisted_values = d["field_values"] if has_field_values else None
        if not isinstance(persisted_values, dict) or not persisted_values:
            persisted_values = None

        record: dict[str, Any] = {
            "business_key": key,
            "classification": cls,
            "classification_label": _CLASS_LABELS.get(cls, cls),
            "remark": _CLASS_REMARKS.get(cls, ""),
            "detail": d.get("detail") or "",
            "field_diffs": diffs,
        }

        if persisted_values is not None:
            # Captured eagerly at reconciliation time (current pipeline,
            # every mode) — authoritative, and the only source available for
            # Auto-mode rows, which have no whole-dataset shadow/snapshot to
            # re-join (see auto_pipeline.nodes._do_finalize).
            record["source_values"] = persisted_values.get("source_values", "")
            record["target_values"] = persisted_values.get("target_values", "")
            for sf, tf, vm in key_specs:
                source_header, target_header = _key_header_names(sf, tf)
                # Fall back through older export naming schemes (first the
                # always-suffixed "(Source)"/"(Target)" an earlier version of
                # this rewire used, then the original "(Original)"/"(Paired)",
                # or the single merged ``sf`` column for a plain key) so a run
                # whose ``field_values`` was persisted before still renders
                # instead of showing blanks.
                if vm is not None:
                    record[source_header] = _first_present(
                        persisted_values, source_header, f"{sf} (Source)", f"{sf} (Original)"
                    )
                    record[target_header] = _first_present(
                        persisted_values, target_header, f"{tf} (Target)", f"{tf} (Paired)"
                    )
                else:
                    record[source_header] = _first_present(
                        persisted_values, source_header, f"{sf} (Source)", sf
                    )
                    record[target_header] = _first_present(
                        persisted_values, target_header, f"{tf} (Target)", sf
                    )
            record["Status"] = _STATUS_BY_CLASS.get(cls, cls.upper())
            for sf, tf in compare_specs:
                record[sf] = persisted_values.get(sf)
                record[tf] = persisted_values.get(tf)
                record[_delta_column_name(sf, tf, compare_specs)] = persisted_values.get(
                    _delta_column_name(sf, tf, compare_specs)
                )
        else:
            # Legacy fallback for a run completed before field values were
            # captured eagerly — reconstruct via the shadow_id/snapshot_id
            # re-join, which may itself come back empty (expired shadow),
            # in which case these columns are simply blank.
            s_row = shadow_by_key.get(key)
            t_row = target_by_key.get(key)
            record["source_values"] = _legacy_vals(s_row, [*bk_src, *cf_src])
            record["target_values"] = _legacy_vals(t_row, [*bk_tgt, *cf_tgt])
            for sf, tf, vm in key_specs:
                source_header, target_header = _key_header_names(sf, tf)
                if vm is not None:
                    record[source_header] = _original_raw_value(s_row, sf, raw_source_df)
                else:
                    record[source_header] = _side_value(s_row, sf)
                record[target_header] = _side_value(t_row, tf)
            record["Status"] = _STATUS_BY_CLASS.get(cls, cls.upper())
            for sf, tf in compare_specs:
                source_val = s_row[sf] if s_row is not None and sf in s_row.index else None
                target_val = t_row[tf] if t_row is not None and tf in t_row.index else None
                record[sf] = _jsonable(source_val)
                record[tf] = _jsonable(target_val)
                record[_delta_column_name(sf, tf, compare_specs)] = _signed_delta(source_val, target_val)
        # Pair ID (see recon_engine.ids) is blank for Manual-mode rows, which
        # have no per-row pair identity to report.
        for sf, tf, vm in key_specs:
            if vm is not None:
                record[f"{sf} Pair ID"] = pair_ids.get(sf)
        rows.append(record)

    return pd.DataFrame(rows)


# IST has no daylight-saving component, so a fixed +5:30 offset from UTC is
# exact — no zoneinfo/pytz dependency needed for this one display conversion.
_IST_OFFSET = timedelta(hours=5, minutes=30)


def _format_ist(value: Any) -> str:
    """Render a UTC ``datetime`` (or ISO string) as IST date & time for display."""
    dt = value
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return dt
    if not isinstance(dt, datetime):
        return "" if dt is None else str(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ist = dt.astimezone(timezone.utc) + _IST_OFFSET
    return ist.strftime("%Y-%m-%d %H:%M:%S") + " IST"


# Business-friendly labels for a value-pairing confidence tier, matching the
# Mapping Review page's TIER_LABEL (frontend/src/reconciliation/steps/
# MappingReviewPage.jsx) for the two tiers that reach the shadow, plus the
# tiers that only ever appear on an unpaired/held-out row.
_CONFIDENCE_LABELS: dict[str, str] = {
    "very_high": "Identity",
    "high": "Verified",
    "medium": "Ambiguous",
    "none": "Unmatched",
    "out_of_scope": "Out of Scope",
}

# "Transformations Applied" sheet's per-value drill-down columns (formerly
# the whole "Mapping Details" sheet) — one block of these nested under each
# value-pairing summary row. Also the exact shape `backend.recon_engine.insights`
# reads/builds (`insights/normalize.py`'s two `mapping_df` construction paths,
# `insights/query.py`'s "mappingUnpaired" filter, `insights/facts.py`'s
# `_unmapped_by_field`) — "Mapping" (the "<source> → <target>" field-pair
# label) MUST stay a real column for that cross-feature contract, even though
# it's now redundant with this sheet's own "Field(s)" summary column.
_MAPPING_DETAIL_COLUMNS = [
    "Mapping", "Source Value", "Target Value", "Status", "Confidence",
    "Corroboration", "Also Candidate For", "Row Count", "Reason", "Pair ID",
]


def _explode_classification_map(detail_df: pd.DataFrame) -> dict[int, str]:
    """Raw source row id -> reconciliation ``classification``, from the
    persisted detail frame's ``source_row_ids`` (JSON-encoded list per
    record) + ``classification`` columns (see ``reconciler._DETAIL_COLUMNS``).
    A row id appearing in more than one record (rare: multi-candidate
    value-pairing duplicates a row across several shadow rows while it
    decides between candidates) keeps the FIRST classification seen — an
    arbitrary but harmless tie-break, since those duplicates are the SAME
    source row's competing candidates, not independent outcomes.
    """
    out: dict[int, str] = {}
    if "source_row_ids" not in detail_df.columns or "classification" not in detail_df.columns:
        return out
    for _, row in detail_df.iterrows():
        raw = row.get("source_row_ids")
        try:
            ids = json.loads(raw) if isinstance(raw, str) else []
        except (TypeError, ValueError):
            ids = []
        cls = str(row.get("classification") or "")
        for rid in ids:
            out.setdefault(int(rid), cls)
    return out


def _explode_reason_map(
    held_out: list[dict[str, Any]], operation_stats: list[dict[str, Any]]
) -> dict[int, str]:
    """Raw source row id -> a human reason it never reached classification:
    either the Value Mapping stage held it out, or a FILTER operation
    dropped it. Anything NOT in this map and NOT in the classification map
    is genuinely unresolved — this map is exactly "the known reasons," so
    unresolved is computed by exclusion, never as a separate enumerated case.
    """
    out: dict[int, str] = {}
    for h in held_out:
        for rid in h.get("row_ids") or []:
            out.setdefault(int(rid), f"Held out by value-pairing: {h.get('reason') or h.get('rule')}")
    for stat in operation_stats:
        if stat.get("kind") != "filter":
            continue
        for rid in stat.get("applied_row_ids") or []:
            out.setdefault(int(rid), f"Filtered out by '{stat.get('op')}'")
    return out


def _operation_field_label(field: str | None, params: dict[str, Any]) -> str:
    """Display label for an operation with no single ``field`` (e.g.
    ``aggregate_group``'s ``by``/``aggregations``, ``concat_fields``'s
    ``fields``) — falls back to the params that name the columns it uses."""
    if field:
        return field
    for key in ("by", "fields"):
        val = params.get(key)
        if isinstance(val, list) and val:
            return ", ".join(str(v) for v in val)
    into = params.get("into")
    return str(into) if into else ""


def _compute_operation_outcomes(
    operation_stats: list[dict[str, Any]],
    detail_df: pd.DataFrame,
    total_raw_rows: int,
    held_out: list[dict[str, Any]],
    value_mappings_by_source_field: dict[str, Any],
) -> list[dict[str, Any]]:
    """Per-operation summary for the "Transformations Applied" sheet.

    For each ENABLED recipe operation (in ``contract.operations`` order),
    PLUS one synthesized "value_pairing" entry per value-mapped business-key
    field (Value Mapping is its own pipeline stage, not a
    ``contract.operations`` entry, but is exactly the kind of transformation
    a key field goes through — synthesizing it here means its per-value
    drill-down is never lost, whether or not a recipe operation ALSO
    happens to touch that same field): what fraction of ALL source rows it
    applied to (``rows_applied``/``pct_applied``), and how those SPECIFIC
    rows resolved:

    * MATCH — the row's shadow record classified as a match.
    * MISMATCH — any KNOWN non-match: a real reconciliation mismatch/missing
      record, a Value Mapping hold-out, or a later filter drop. The specific
      reason stays visible in that field's ``detail_rows`` (when it's a
      value-mapped business key) rather than being lost in the rollup.
    * UNRESOLVED — found in NEITHER the classification map nor the reason
      map. A residual bucket computed purely by exclusion — never an
      enumerated case — so it surfaces exactly the rows our own accounting
      can't explain, instead of silently counting them as an ordinary
      mismatch.
    """
    classification_map = _explode_classification_map(detail_df)
    reason_map = _explode_reason_map(held_out, operation_stats)

    def _pct(n: int, denom: int) -> float:
        return round((n / denom) * 100.0, 1) if denom else 0.0

    def _classify(ids: list[int]) -> tuple[int, int, int]:
        match = mismatch = unresolved = 0
        for rid in ids:
            cls = classification_map.get(rid)
            if cls == "match":
                match += 1
            elif cls is not None or rid in reason_map:
                mismatch += 1
            else:
                unresolved += 1
        return match, mismatch, unresolved

    def _outcome(
        op: str, field_label: str, applied_ids: list[int], detail_rows: list[Any],
        mapping_label: str | None = None,
    ) -> dict[str, Any]:
        match, mismatch, unresolved = _classify(applied_ids)
        applied_count = len(applied_ids)
        return {
            "op": op,
            "field_label": field_label,
            "rows_applied": applied_count,
            "pct_applied": _pct(applied_count, total_raw_rows),
            "pct_match": _pct(match, applied_count),
            "pct_mismatch": _pct(mismatch, applied_count),
            "pct_unresolved": _pct(unresolved, applied_count),
            "detail_rows": detail_rows,
            # The "<source> → <target>" label — carried through onto each
            # detail row's "Mapping" column for the Insights cross-feature
            # contract (see the module comment on _MAPPING_DETAIL_COLUMNS).
            "mapping_label": mapping_label,
        }

    outcomes: list[dict[str, Any]] = [
        _outcome(
            stat.get("op"),
            _operation_field_label(stat.get("field"), stat.get("params") or {}),
            stat.get("applied_row_ids") or [],
            [],
        )
        for stat in operation_stats
    ]

    # Value pairing "applies to" every row that survived filtering (i.e.
    # reached that stage) — the union of every FILTER op's dropped rows,
    # subtracted from the full raw row-id range.
    filtered_out_ids: set[int] = set()
    for stat in operation_stats:
        if stat.get("kind") == "filter":
            filtered_out_ids.update(stat.get("applied_row_ids") or [])
    survived_ids = [i for i in range(total_raw_rows) if i not in filtered_out_ids]

    for source_field, vm in value_mappings_by_source_field.items():
        outcomes.append(
            _outcome(
                "value_pairing", source_field, survived_ids, list(vm.matches),
                mapping_label=f"{source_field} → {vm.target_field}",
            )
        )

    return outcomes


def _value_pairing_outcomes_from_contract_only(
    value_mappings_by_source_field: dict[str, Any],
) -> list[dict[str, Any]]:
    """Fallback for a run whose raw source snapshot can no longer be
    reloaded (e.g. an Auto-mode streaming run's snapshot id is a synthetic
    identifier, not a real reloadable one) — no recipe-operation stats are
    derivable without replaying the contract, but ``contract.value_mappings``
    needs no replay at all, so this still shows the per-value drill-down and
    a best-effort match/mismatch split by distinct-value row count (no true
    % of total source rows, and no unresolved bucket — both need the raw
    row lineage this path doesn't have).
    """
    outcomes: list[dict[str, Any]] = []
    for source_field, vm in value_mappings_by_source_field.items():
        matched_rows = sum(m.row_count for m in vm.matches if m.target_value is not None)
        unpaired_rows = sum(m.row_count for m in vm.matches if m.target_value is None)
        total = matched_rows + unpaired_rows
        outcomes.append(
            {
                "op": "value_pairing",
                "field_label": source_field,
                "rows_applied": total,
                "pct_applied": None,
                "pct_match": round((matched_rows / total) * 100.0, 1) if total else 0.0,
                "pct_mismatch": round((unpaired_rows / total) * 100.0, 1) if total else 0.0,
                "pct_unresolved": 0.0,
                "detail_rows": list(vm.matches),
                "mapping_label": f"{source_field} → {vm.target_field}",
            }
        )
    return outcomes


def _find_value_mapping(contract: Any, target_field: str | None) -> Any | None:
    """The contract's ``ValueMapping`` for a given target field, matched by
    TARGET field name — stable across connector variants, never a literal
    string like ``"PRDID"``."""
    if contract is None or target_field is None:
        return None
    return next((vm for vm in contract.value_mappings if vm.target_field == target_field), None)


def _summarize_value_mapping(vm: Any | None) -> tuple[int, int]:
    """Distinct-VALUE matched/unmatched counts for one field pair's value
    mapping — a source value with two accepted candidates (see
    value_pairing.pipeline) counts once, not twice, mirroring the Mapping
    Review page's own summary charts."""
    if vm is None:
        return 0, 0
    matched = {m.source_value for m in vm.matches if m.target_value is not None}
    unmatched = {m.source_value for m in vm.matches if m.target_value is None}
    return len(matched), len(unmatched)


def build_comparison_workbook(run_id: str) -> bytes:
    """Build the downloadable, colour-coded 3-sheet comparison workbook (.xlsx).

    Read-only reconstruction — reconciliation logic is untouched; values are
    re-derived verbatim via :func:`build_enriched_detail`; the
    "Transformations Applied" sheet is re-derived by replaying the approved
    contract's operations against the immutable raw source snapshot (see
    :func:`_compute_operation_outcomes`) — the exact same deterministic
    reproduction :func:`build_shadow_preview` relies on. Exactly three sheets:

    1. ``Summary`` — the **Results** table first (every category, even at
       count 0, with Count and % of Total, each row filled with the
       category's colour), then a trimmed **Run Information** block (Run
       Status / Created At in IST / Created By only), then a native pie
       chart for the overall run results plus one more pie chart per
       value-mapped business-key pair (however many the contract has),
       showing that pair's matched/unmatched distribution.
    2. ``All Records`` — matches, quantity mismatches, missing-in-target, and
       extra-in-target records (a business key present on only one side,
       split by which side) stacked into one flat, field-level table, sorted
       issues-first and colour-coded by status. Bold white header on dark
       blue, frozen, with AutoFilter; widths auto-fit. Column set is computed
       per contract (see :func:`_export_columns_for_contract`) — scales to
       however many key/compare pairs the contract has.
    3. ``Transformations Applied`` — one summary row per DISTINCT recipe
       operation that actually ran: Transformation, Field(s), Rows Applied,
       % Applied, % Match, % Mismatch. No per-value pairing drill-down —
       that detail lives in the Mapping Review page, not this export.
    """
    from openpyxl import Workbook
    from openpyxl.chart import PieChart, Reference
    from openpyxl.chart.label import DataLabelList
    from openpyxl.chart.marker import DataPoint
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    init_storage()
    run = run_store.get_run(run_id)
    if run is None:
        raise KeyError(f"Unknown run '{run_id}'.")
    result = result_store.get_result_for_run(run_id)
    if result is None:
        raise KeyError(f"No reconciliation result found for run '{run_id}'.")

    contract = contract_store.get_contract(run.contract_id, run.contract_version)
    contract = _effective_contract(contract, run_id)
    enriched = build_enriched_detail(run_id)
    summary = result.summary.model_dump()

    # Every key pair that actually went through value-pairing (i.e. has a
    # ValueMapping) — however many there are, in contract order.
    mapped_specs = [
        (sf, tf, vm) for sf, tf, vm in _business_key_export_specs(contract) if vm is not None
    ]

    # Per-operation (and per-value-pairing-field) outcome summary, shared by
    # the Summary sheet's structured table and the Transformations Applied
    # sheet's full detail. Requires replaying the approved contract against
    # the immutable raw source snapshot — reloadable for a normal Manual-mode
    # run, but an Auto-mode streaming run's snapshot id is a synthetic
    # identifier that was never meant to be reloaded this way; degrade to a
    # value-pairing-only summary (still no functionality lost relative to the
    # old sheet, which needed no snapshot at all) rather than failing the
    # whole export.
    value_mappings_by_source_field = {vm.source_field: vm for vm in contract.value_mappings}
    try:
        raw_source_df = snapshot_store.load_snapshot_frame(run.source_snapshot_id)
        # `run.created_at` anchors any run_date-dependent op (date_window_filter,
        # relative_date_reassign) to when the run actually executed, not to
        # whenever this export happens to be downloaded.
        built = build_shadow_source(contract, raw_source_df, run_date=run.created_at)
        detail_df = result_store.load_result_frame_any(result.result_id)
        operation_outcomes = _compute_operation_outcomes(
            built.operation_stats, detail_df, len(raw_source_df), built.held_out,
            value_mappings_by_source_field,
        )
    except Exception:  # noqa: BLE001 - degrade, never fail the export over this
        logger.warning(
            "Transformations Applied: could not replay run %s's source snapshot; "
            "falling back to a value-pairing-only summary.", run_id, exc_info=True,
        )
        operation_outcomes = _value_pairing_outcomes_from_contract_only(value_mappings_by_source_field)

    bold = Font(bold=True)
    block_header = Font(bold=True, size=12)

    def _autofit(ws: Any) -> None:
        widths: dict[int, int] = {}
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is None:
                    continue
                longest = max((len(line) for line in str(cell.value).splitlines()), default=0)
                widths[cell.column] = max(widths.get(cell.column, 0), longest)
        for idx, width in widths.items():
            ws.column_dimensions[get_column_letter(idx)].width = min(max(width + 2, 10), 80)

    def _labeled_pie(title: str, data_ref: Reference, cat_ref: Reference, colors: list[str]) -> PieChart:
        chart = PieChart()
        chart.title = title
        chart.add_data(data_ref, titles_from_data=False)
        chart.set_categories(cat_ref)
        chart.dataLabels = DataLabelList()
        chart.dataLabels.showVal = True
        chart.height = 8
        chart.width = 12
        points = []
        for idx, color in enumerate(colors):
            point = DataPoint(idx=idx)
            point.graphicalProperties.solidFill = color
            points.append(point)
        chart.series[0].data_points = points
        return chart

    wb = Workbook()

    # ── Sheet 1: Summary ─────────────────────────────────────────────────────
    ws1 = wb.active
    ws1.title = "Summary"

    # -- Results table (top) --
    ws1.cell(row=1, column=1, value="Results").font = block_header
    for col, name in enumerate(("Category", "Count", "% of Total"), start=1):
        ws1.cell(row=2, column=col, value=name).font = bold

    total = int(summary.get("total", 0))
    results_start_row = 3
    r = results_start_row
    for field in _SUMMARY_ORDER:
        label, status, _raw_classes = _SUMMARY_BUCKETS[field]
        count = int(summary.get(field, 0))
        pct = (count / total * 100.0) if total else 0.0
        fill = PatternFill("solid", fgColor=_STATUS_FILL[status])
        cells = [
            ws1.cell(row=r, column=1, value=label),
            ws1.cell(row=r, column=2, value=count),
            ws1.cell(row=r, column=3, value=f"{pct:.1f}%"),
        ]
        for c in cells:
            c.fill = fill
        r += 1
    results_end_row = r - 1
    # Total row — bold, no category colour (not part of the legend).
    for col, value in ((1, "Total"), (2, total), (3, "100.0%" if total else "0.0%")):
        ws1.cell(row=r, column=col, value=value).font = bold
    r += 2  # blank spacer

    # -- Run Information (trimmed: Run Status / Created At (IST) / Created By) --
    ws1.cell(row=r, column=1, value="Run Information").font = block_header
    r += 1
    run_info = [
        ("Run Status", getattr(run.status, "value", str(run.status))),
        ("Created At", _format_ist(run.created_at)),
        ("Created By", run.created_by),
    ]
    for label, value in run_info:
        ws1.cell(row=r, column=1, value=label).font = bold
        ws1.cell(row=r, column=2, value=value)
        r += 1

    # -- Transformations Applied (structured table) --
    # Replaces the old per-key-pair "Mapping Review" pie charts with the same
    # per-operation / per-value-pairing-field summary the "Transformations
    # Applied" sheet carries in full — condensed here (no per-value
    # drill-down) for an at-a-glance view without leaving the Summary sheet.
    table_col = 5  # column E
    tr = 1
    ws1.cell(row=tr, column=table_col, value="Transformations Applied").font = block_header
    tr += 1
    ta_headers = ["Transformation", "Field(s)", "% Applied", "% Match", "% Mismatch", "% Unresolved"]
    for offset, name in enumerate(ta_headers):
        ws1.cell(row=tr, column=table_col + offset, value=name).font = bold
    tr += 1
    for outcome in operation_outcomes:
        values = [
            outcome["op"], outcome["field_label"], outcome["pct_applied"],
            outcome["pct_match"], outcome["pct_mismatch"], outcome["pct_unresolved"],
        ]
        for offset, value in enumerate(values):
            cell = ws1.cell(row=tr, column=table_col + offset, value=value)
            if offset == 5 and isinstance(value, (int, float)) and value > 0:
                cell.fill = PatternFill("solid", fgColor="FFA500")
        tr += 1

    # -- Chart (bottom): overall run results only — the per-key-pair mapping
    # pie charts were replaced by the structured table above. --
    charts_row = max(r, tr) + 2
    ws1.cell(row=charts_row - 1, column=1, value="Charts").font = block_header

    overall_chart = _labeled_pie(
        "Overall Run Results",
        Reference(ws1, min_col=2, min_row=results_start_row, max_row=results_end_row),
        Reference(ws1, min_col=1, min_row=results_start_row, max_row=results_end_row),
        [_STATUS_FILL[_SUMMARY_BUCKETS[field][1]] for field in _SUMMARY_ORDER],
    )
    ws1.add_chart(overall_chart, f"{get_column_letter(1)}{charts_row}")

    ws1.freeze_panes = "A2"
    _autofit(ws1)

    # ── Sheet 2: All Records ─────────────────────────────────────────────────
    ws2 = wb.create_sheet("All Records")
    columns = _export_columns_for_contract(contract)
    # Delta columns are stored signed (source - target; see _signed_delta,
    # shared with the Insights netDelta calculation, which needs the sign to
    # net positive/negative breaks against each other) — the export itself
    # always shows the non-negative magnitude of the mismatch.
    all_records_compare_specs = _compare_field_export_specs(contract)
    delta_col_names = {
        _delta_column_name(sf, tf, all_records_compare_specs) for sf, tf in all_records_compare_specs
    }
    header_fill = PatternFill("solid", fgColor=_HEADER_FILL)
    header_font = Font(bold=True, color="FFFFFF")
    for col, name in enumerate(columns, start=1):
        c = ws2.cell(row=1, column=col, value=name)
        c.font = header_font
        c.fill = header_fill

    row_idx = 2
    for field in _ALL_RECORDS_ORDER:
        _label, bucket_status, raw_classes = _SUMMARY_BUCKETS[field]
        subset = enriched if enriched.empty else enriched[enriched["classification"].isin(raw_classes)]
        for _, rec in subset.iterrows():
            status = rec.get("Status") or bucket_status
            fill = PatternFill("solid", fgColor=_STATUS_FILL.get(status, "FFFFFF"))
            for col, name in enumerate(columns, start=1):
                value = rec.get(name)
                if name in delta_col_names and isinstance(value, (int, float)) and not isinstance(value, bool):
                    value = abs(value)
                cell = ws2.cell(row=row_idx, column=col, value=value)
                cell.fill = fill
            row_idx += 1

    ws2.freeze_panes = "A2"
    ws2.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{max(1, row_idx - 1)}"
    _autofit(ws2)

    # ── Sheet 3: Transformations Applied ─────────────────────────────────────
    # One row per DISTINCT recipe operation (plus one synthesized row per
    # value-mapped business-key field) — just the op-level summary; no
    # "% Unresolved" and no per-value drill-down columns/rows (task spec).
    ws3 = wb.create_sheet("Transformations Applied")

    _OP_SUMMARY_COLUMNS = ["Transformation", "Field(s)", "Rows Applied", "% Applied", "% Match", "% Mismatch"]
    for col, name in enumerate(_OP_SUMMARY_COLUMNS, start=1):
        c = ws3.cell(row=1, column=col, value=name)
        c.font = header_font
        c.fill = header_fill

    # `operation_outcomes` was already computed above (shared with the
    # Summary sheet's structured table).
    row_idx = 2
    for outcome in operation_outcomes:
        summary_values = [
            outcome["op"], outcome["field_label"], outcome["rows_applied"],
            outcome["pct_applied"], outcome["pct_match"], outcome["pct_mismatch"],
        ]
        for col, value in enumerate(summary_values, start=1):
            cell = ws3.cell(row=row_idx, column=col, value=value)
            cell.font = bold
        row_idx += 1

    ws3.freeze_panes = "A2"
    ws3.auto_filter.ref = f"A1:{get_column_letter(len(_OP_SUMMARY_COLUMNS))}{max(1, row_idx - 1)}"
    _autofit(ws3)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _with_overlap_pct(alignment: dict[str, Any]) -> dict[str, Any]:
    src_total = alignment.get("source_total") or 0
    alignment["overlap_pct"] = (
        round((alignment.get("source_included", 0) / src_total) * 100.0, 1) if src_total else 0
    )
    return alignment


def compute_snapshot_date_alignment(
    source_snapshot_id: str, target_snapshot_id: str
) -> dict[str, Any]:
    """Pre-run date-overlap diagnostic between two raw snapshots.

    Lets the wizard show source/target date ranges + overlap % before a run is
    executed. Read-only; does not alter reconciliation."""
    from backend.excel_comparator.core.date_alignment import build_alignment

    init_storage()
    source_df = snapshot_store.load_snapshot_frame(source_snapshot_id)
    target_df = snapshot_store.load_snapshot_frame(target_snapshot_id)
    return _with_overlap_pct(build_alignment(source_df, target_df))


def compute_run_date_alignment(run: Any) -> dict[str, Any]:
    """Compute date-range overlap between a run's source (shadow) and target
    frames using the shared date-alignment analysis. Tolerant of expired
    shadows / missing frames (returns a skipped result)."""
    from backend.excel_comparator.core.date_alignment import build_alignment

    source_df: pd.DataFrame | None = None
    target_df: pd.DataFrame | None = None
    try:
        if run.shadow_id:
            source_df = shadow_store.load_shadow_frame(run.shadow_id)
    except Exception:  # noqa: BLE001
        logger.warning("Date alignment: shadow frame unavailable for run %s", run.run_id)
    try:
        target_df = snapshot_store.load_snapshot_frame(run.target_snapshot_id)
    except Exception:  # noqa: BLE001
        logger.warning("Date alignment: target frame unavailable for run %s", run.run_id)

    if source_df is None or target_df is None:
        return {
            "source_date_column": None, "target_date_column": None,
            "source_range": None, "target_range": None, "overlap": None,
            "has_overlap": False, "overlap_pct": 0,
            "note": "Source and/or target frame unavailable (shadow may have expired).",
        }

    return _with_overlap_pct(build_alignment(source_df, target_df))


# ── maintenance ────────────────────────────────────────────────────────────

def cleanup_expired_shadows(actor: str = "system") -> list[str]:
    """TTL cleanup entry point (call from a scheduled job / startup)."""
    init_storage()
    removed = shadow_store.cleanup_expired()
    for shadow_id in removed:
        audit_store.record(
            AuditAction.SHADOW_EXPIRED, entity_type="shadow", entity_id=shadow_id, actor=actor,
        )
    return removed
