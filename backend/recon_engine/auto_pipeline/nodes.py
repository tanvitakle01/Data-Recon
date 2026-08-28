"""Auto-mode pipeline nodes.

Each node calls the exact same business-logic functions the manual wizard's
routes already call (never HTTP, never a parallel re-implementation), and
translates their existing exceptions into the graph's hard-stop signal. Manual
mode's own endpoints are never touched by anything in this module.

No field, entity, or business-key name is ever hardcoded here. Every name used
to fetch data comes from the mapping sheet's LLM extraction
(``identification``), verified against the live connector's real schema
before use (:mod:`backend.recon_engine.auto_pipeline.field_matching`). Which
extracted, verified column plays which business role (Product/Location/Date/
Quantity) is detected the same way manual mode's "AI-mapping" flow detects it
— by alias, from the column's real name — never assumed from a fixed literal.
The one legitimate default anywhere in this path is a join key: when the sheet
names none, the live schema's own relationship suggestion is used, exactly as
manual mode's Join Builder canvas defaults it — never as a substitute for
something the sheet DID provide.

Data-aligned streaming batches: full source/target datasets are never pulled
into memory at once. ``resolve_schema``/``compile_contract`` resolve
entities/fields/roles/the approved contract from small, bounded preview
fetches only; ``plan_date_batches`` builds a record-count-bounded, date-
aligned batch plan from a cheap column-only pull; ``run_batches`` then
extracts, pairs, verifies, reconciles, appends, and checkpoints one date
window at a time, so peak memory stays flat regardless of total dataset size
and a hard failure resumes from exactly the batch it stopped at.
"""

from __future__ import annotations

import time
from typing import Any, Callable

import pandas as pd
from langgraph.errors import GraphBubbleUp

from backend.API_conn.connectors import registry
from backend.API_conn.connectors.ibp_metadata_service import IBPMetadataService
from backend.API_conn.connectors.s4_metadata_service import S4MetadataService
from backend.excel_comparator.core.date_alignment import parse_dates
from backend.recon_engine import heartbeat, ids, run_registry, service
from backend.recon_engine.run_registry import CooperativeCancellation, CooperativeSuspension
from backend.recon_engine.engine.executor import build_shadow_source
from backend.recon_engine.engine.reconciler import reconcile
from backend.recon_engine.llm import clear_llm_call_context, set_llm_call_context
from backend.recon_engine.models.results import excluded_unmapped_counts
from backend.recon_engine.models.run import ReconciliationRun, RunStatus
from backend.recon_engine.models.value_mapping import ValueMapping, ValueMatch
from backend.recon_engine.storage import (
    contract_store,
    corroboration_store,
    error_event_store,
    pipeline_run_store,
    result_store,
    run_store,
    snapshot_store,
)
from backend.recon_engine.value_pairing.corroborate import corroboration_evidence
from backend.recon_engine.value_pairing.extraction import distinct_values
from backend.recon_engine.value_pairing.pipeline import _pair_batch

from backend.recon_engine.auto_pipeline.candidate_keys import identify_candidate_keys
from backend.recon_engine.auto_pipeline.date_batching import (
    DateBatch,
    client_for,
    entity_and_field_for_batch,
    fetch_date_column,
    plan_batches,
)
from backend.recon_engine.auto_pipeline.field_matching import (
    detect_roles_for_columns,
    match_proposed_to_schema,
)
from backend.recon_engine.auto_pipeline.interrupts import (
    resolve_entity_or_ask,
    resolve_field_or_ask,
    resolve_join_key_or_ask,
)
from backend.recon_engine.auto_pipeline.state import AutoRunState, SideState

_REQUIRED_ROLES = ("product", "location", "date", "quantity")
_CANDIDATE_KEY_ROLES = ("product", "location")
_BUSINESS_KEY_ROLES = ("date", "quantity")


# ── step 1: select connector/entity ──────────────────────────────────────────

def _select_side(identification: dict[str, Any], role: str) -> SideState:
    kind = identification.get("kind")
    allowed = {c["kind"] for c in registry.get_configured_connectors(role=role)}
    if not kind or kind not in allowed:
        raise RuntimeError(
            f"The {role} system was not resolved to a configured connector from the "
            f"mapping sheet (got kind={kind!r})."
        )
    primary_entity = identification.get("primary_entity")
    if not primary_entity:
        raise RuntimeError(f"The {role} entity was not resolved from the mapping sheet.")
    return {
        "kind": kind,
        "connector_id": identification.get("connector_id"),
        "primary_entity": primary_entity,
        "fields": list(identification.get("fields") or []),
        "entities": list(identification.get("entities") or []),
        "join_type": identification.get("join_type"),
        "join_keys": list(identification.get("join_keys") or []),
    }


def _do_select_source(state: AutoRunState) -> dict[str, Any]:
    if (state.get("source") or {}).get("kind") == "upload":
        # Already fully resolved by the caller (service.ingest_snapshot) before
        # the graph started — nothing to select from a live connector.
        return {}
    return {"source": _select_side(state["identification"]["source"], registry.SOURCE)}


def _do_select_target(state: AutoRunState) -> dict[str, Any]:
    if (state.get("target") or {}).get("kind") == "upload":
        return {}
    return {"target": _select_side(state["identification"]["target"], registry.TARGET)}


# ── step 2: resolve schema — entity/field/join resolution + roles ───────────
#
# No full extraction here — only metadata calls (get_entities/get_entity_
# properties/get_entity_relationships, all schema-only, no rows) plus ONE
# small, bounded preview fetch per side (client.preview_join/preview_entity,
# already capped at PREVIEW_SAMPLE_TOP/10 rows) to get REAL column names for
# candidate-key identification and business-role detection — the only two
# things that ever needed data before, and both only ever needed the column
# names, never the values.

def _live_property_names(client: S4MetadataService, entity: str) -> list[str]:
    return [p["name"] for p in client.get_entity_properties(entity)]


def _resolve_s4_spec(side: SideState, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    client = S4MetadataService()
    live_entities = [e["name"] for e in client.get_entities()]
    raw_primary = side["primary_entity"]
    # Entity-not-resolved is RECOVERABLE via a single answer (see interrupts.py)
    # — pauses and re-asks with live-closeness chips rather than hard-stopping.
    primary = resolve_entity_or_ask(side=role, kind="s4", attempted=raw_primary, live_names=live_entities)

    requested_fields = list(side.get("fields") or [])
    if not requested_fields:
        raise RuntimeError(
            f"The mapping sheet did not extract any source fields for {primary!r} — "
            "nothing to verify or fetch."
        )

    raw_joined = [e for e in (side.get("entities") or []) if e != raw_primary]
    joined_entities = [
        resolve_entity_or_ask(side=role, kind="s4", attempted=e, live_names=live_entities)
        for e in raw_joined
    ]

    primary_live = _live_property_names(client, primary)
    primary_matched, _unmatched = match_proposed_to_schema(requested_fields, primary_live)

    join_live: dict[str, list[str]] = {}
    join_matched: dict[str, list[str]] = {}
    for entity in joined_entities:
        entity_live = _live_property_names(client, entity)
        join_live[entity] = entity_live
        matched, _unmatched = match_proposed_to_schema(requested_fields, entity_live)
        join_matched[entity] = matched

    if not primary_matched and not any(join_matched.values()):
        # Field/business-field not resolved is likewise RECOVERABLE — ask for
        # one live field to unblock rather than hard-stopping outright.
        primary_matched = resolve_field_or_ask(
            side=role, kind="s4", attempted_fields=requested_fields, live_fields=primary_live
        )

    joins: list[dict[str, Any]] = []
    if joined_entities:
        relationships = client.get_entity_relationships(primary)
        by_target = {r["target_entity"]: r for r in relationships}
        llm_keys = [
            (k["left"], k["right"])
            for k in (side.get("join_keys") or [])
            if k.get("left") and k.get("right")
        ]

        for entity in joined_entities:
            keys: list[dict[str, str]] | None = None
            if llm_keys:
                # The sheet named join keys — verify each against BOTH
                # entities' live schemas before trusting it. Unlike entity
                # *properties* (safely filtered by S4MetadataService itself),
                # join *keys* are placed straight into the OData $select with
                # no such filtering — an unvalidated key is exactly how a bad
                # sheet-derived field reached a live query unfiltered before.
                verified: list[dict[str, str]] = []
                for left, right in llm_keys:
                    left_matched, _ = match_proposed_to_schema([left], primary_live)
                    right_matched, _ = match_proposed_to_schema([right], join_live[entity])
                    if left_matched and right_matched:
                        verified.append({"left": left_matched[0], "right": right_matched[0]})
                keys = verified or None

            if not keys:
                # The sheet named no (verified) join key — the one legitimate
                # default anywhere in this path: the live schema's own
                # relationship suggestion, exactly what manual mode's Join
                # Builder canvas defaults to. Never a substitute for a key the
                # sheet DID provide — only for one it genuinely didn't.
                rel = by_target.get(entity)
                suggested_keys = rel["suggested_keys"] if rel else []
                if suggested_keys:
                    keys = [{"left": k, "right": k} for k in suggested_keys]
                else:
                    # Join key missing is the third RECOVERABLE case — ask for
                    # a key shared by both entities' live schemas.
                    keys = resolve_join_key_or_ask(
                        side=role,
                        kind="s4",
                        primary_entity=primary,
                        joined_entity=entity,
                        primary_props=primary_live,
                        joined_props=join_live[entity],
                    )

            # An entity contributing no verified business field to this run
            # still needs a concrete, non-empty properties list — its own live
            # keys (real, already-verified structural identifiers, never a
            # guessed business field) rather than an empty list, which would
            # fall through to S4MetadataService's own generic "first few
            # properties" default (a silent substitution this module must
            # never make).
            props = join_matched[entity] or client.get_entity_keys(entity)
            joins.append(
                {
                    "entity": entity,
                    "properties": props,
                    "type": side.get("join_type") or "left",
                    "keys": keys,
                }
            )

    primary_props = primary_matched or client.get_entity_keys(primary)
    spec = {
        "primary": {"entity": primary, "properties": primary_props},
        "joins": joins,
    }
    return spec, {"primary_entity": primary, "entities": [primary, *joined_entities]}


def _resolve_ibp_spec(side: SideState, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    client = IBPMetadataService()
    live_entities = [e["name"] for e in client.get_entities()]
    primary = resolve_entity_or_ask(
        side=role, kind="ibp", attempted=side["primary_entity"], live_names=live_entities
    )
    requested_fields = list(side.get("fields") or [])
    if not requested_fields:
        raise RuntimeError(
            f"The mapping sheet did not extract any target fields for {primary!r} — "
            "nothing to verify or fetch."
        )
    live_selectable = [
        p["name"] for p in client.get_entity_properties(primary) if p.get("selectable")
    ]
    matched, _unmatched = match_proposed_to_schema(requested_fields, live_selectable)
    if not matched:
        matched = resolve_field_or_ask(
            side=role, kind="ibp", attempted_fields=requested_fields, live_fields=live_selectable
        )
    spec = {"entity": primary, "selected": matched}
    return spec, {"primary_entity": primary}


_SPEC_RESOLVERS: dict[str, Callable[[SideState, str], tuple[dict[str, Any], dict[str, Any]]]] = {
    "s4": _resolve_s4_spec,
    "ibp": _resolve_ibp_spec,
}


def _preview_columns(kind: str, spec: dict[str, Any]) -> list[str]:
    """A small, bounded preview fetch (already capped by the metadata
    service's own preview methods) — just enough to get real column names,
    never a source of full rows."""
    if kind == "s4":
        client = S4MetadataService()
        df = client.preview_join(spec)
    elif kind == "ibp":
        client = IBPMetadataService()
        df = client.preview_entity(spec["entity"], spec["selected"])
    else:
        raise RuntimeError(f"No schema previewer for connector kind {kind!r}.")
    return [str(c) for c in df.columns]


def _resolve_upload_side_schema(side: SideState) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """No live connector to resolve against — the caller (service.
    ingest_snapshot, via start_auto_run_from_data_state) already fully
    populated ``side["columns"]``/``["snapshot_id"]`` before the graph
    started. ``spec`` carries just enough for plan_date_batches/run_batches
    to locate the already-ingested snapshot."""
    if not side.get("columns"):
        raise RuntimeError("Uploaded data has no columns to resolve a schema from.")
    return {"snapshot_id": side["snapshot_id"]}, {"primary_entity": side["primary_entity"]}, list(side["columns"])


def _resolve_side_schema(side: SideState, role: str) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    if side["kind"] == "upload":
        return _resolve_upload_side_schema(side)
    resolver = _SPEC_RESOLVERS.get(side["kind"])
    if resolver is None:
        raise RuntimeError(f"No schema resolver for connector kind {side['kind']!r}.")
    spec, resolved = resolver(side, role)
    columns = _preview_columns(side["kind"], spec)
    if not columns:
        raise RuntimeError(
            f"{role.capitalize()} schema preview returned no columns "
            f"(entity={resolved.get('primary_entity')!r})."
        )
    return spec, resolved, columns


def _do_resolve_schema(state: AutoRunState) -> dict[str, Any]:
    source_spec, source_resolved, source_columns = _resolve_side_schema(state["source"], registry.SOURCE)
    target_spec, target_resolved, target_columns = _resolve_side_schema(state["target"], registry.TARGET)

    candidate_keys = identify_candidate_keys(
        source_columns, target_columns, mapping_sheet_context=state.get("mapping_sheet")
    )
    if candidate_keys.get("degraded"):
        raise RuntimeError(
            f"Candidate-key identification failed: {candidate_keys.get('degraded_reason')}"
        )
    missing = [
        f"{side}.{role}"
        for side in ("source", "target")
        for role in _CANDIDATE_KEY_ROLES
        if not candidate_keys[side][role]["field"]
    ]
    if missing:
        raise RuntimeError(
            f"Could not identify a candidate key for {missing} from the previewed "
            f"columns (source={source_columns!r}, target={target_columns!r})."
        )

    source_bkey_roles = detect_roles_for_columns(source_columns)
    target_bkey_roles = detect_roles_for_columns(target_columns)
    missing_source = [r for r in _BUSINESS_KEY_ROLES if r not in source_bkey_roles]
    missing_target = [r for r in _BUSINESS_KEY_ROLES if r not in target_bkey_roles]
    if missing_source or missing_target:
        raise RuntimeError(
            "Could not detect all required business-key roles (date/quantity) for "
            f"reconciliation — source missing {missing_source or 'none'} "
            f"(columns: {source_columns!r}), target missing "
            f"{missing_target or 'none'} (columns: {target_columns!r})."
        )

    source_roles = {role: candidate_keys["source"][role]["field"] for role in _CANDIDATE_KEY_ROLES}
    target_roles = {role: candidate_keys["target"][role]["field"] for role in _CANDIDATE_KEY_ROLES}
    source_roles.update({role: source_bkey_roles[role] for role in _BUSINESS_KEY_ROLES})
    target_roles.update({role: target_bkey_roles[role] for role in _BUSINESS_KEY_ROLES})

    updated_source = dict(state["source"])
    updated_source.update(source_resolved)
    updated_source["columns"] = source_columns
    updated_target = dict(state["target"])
    updated_target.update(target_resolved)
    updated_target["columns"] = target_columns

    return {
        "source": updated_source,
        "target": updated_target,
        "source_spec": source_spec,
        "target_spec": target_spec,
        "candidate_keys": candidate_keys,
        "source_field_roles": source_roles,
        "target_field_roles": target_roles,
    }


# ── step 3: compile + approve the contract (ONCE, before batching) ──────────

def _do_compile_contract(state: AutoRunState) -> dict[str, Any]:
    source_roles = state.get("source_field_roles") or {}
    target_roles = state.get("target_field_roles") or {}
    missing = [
        role for role in _REQUIRED_ROLES
        if role not in source_roles or role not in target_roles
    ]
    if missing:
        raise RuntimeError(
            f"Missing a detected business role for {missing} on one or both sides — "
            "cannot build the business key/compare fields for reconciliation."
        )

    business_key = [
        {"source_field": source_roles[role], "target_field": target_roles[role]}
        for role in ("product", "location", "date")
    ]
    compare_fields = [
        {
            "source_field": source_roles["quantity"],
            "target_field": target_roles["quantity"],
            "match_type": "exact",
        },
    ]
    actor = state.get("actor", "auto")

    # value_mappings is empty at compile time — under streaming, value pairing
    # only ever resolves incrementally, one batch at a time (see
    # run_batches/_finalize_batch_shadow below), so there is no complete
    # dataset-wide ValueMapping yet for the compiler to bake in. Each batch
    # substitutes its OWN batch-scoped value_mappings onto a throwaway copy of
    # this approved contract (see _do_run_batches) — the stored, approved
    # contract itself keeps operations/business_key/compare_fields only.
    draft, degraded_reason = service.compile_draft(
        mapping_sheet=state.get("mapping_sheet") or [],
        rules="",
        business_key=business_key,
        compare_fields=compare_fields,
        value_mappings=[],
        source_schema=state["source"]["columns"],
        target_schema=state["target"]["columns"],
        comparison_type=state.get("comparison_type") or "auto",
        source_type=state["source"]["kind"],
        target_type=state["target"]["kind"],
        actor=actor,
    )
    if degraded_reason is not None:
        # Auto mode has no human checkpoint to catch a silently stub-compiled
        # contract the way Manual mode's approval step would — hard-stop
        # regardless of the global RECON_GROQ_STRICT setting rather than let
        # deterministic regex rules silently stand in for the LLM compiler.
        raise RuntimeError(
            f"Contract compilation degraded to the deterministic stub compiler: "
            f"{degraded_reason} — Auto mode requires a real LLM compile."
        )
    approved = service.approve_contract(draft, approved_by=actor)
    return {"contract_id": approved.contract_id, "contract_version": approved.contract_version}


# ── step 4: plan the date-aligned streaming batches ──────────────────────────

def _fetch_side_date_column(kind: str, spec: dict[str, Any], date_field: str) -> pd.Series:
    """The date column for one side, for batch planning — a cheap paginated
    live pull for a connector side, or the already-local snapshot's own
    column (parsed with the same flexible, upload-safe parser used elsewhere
    for uploaded data — see date_batching._normalized_date_counts, which
    passes an already-datetime64 series like this one straight through
    rather than re-parsing it with the connectors' rigid dd.mm.yyyy format)
    for an "upload" side."""
    if kind == "upload":
        df = snapshot_store.load_snapshot_frame(spec["snapshot_id"])
        return parse_dates(df[date_field])
    entity, _ = entity_and_field_for_batch(spec, kind, date_field)
    return fetch_date_column(client_for(kind), entity, date_field)


def _do_plan_date_batches(state: AutoRunState) -> dict[str, Any]:
    source_kind = state["source"]["kind"]
    target_kind = state["target"]["kind"]
    source_date_field = state["source_field_roles"]["date"]
    target_date_field = state["target_field_roles"]["date"]

    source_dates = _fetch_side_date_column(source_kind, state["source_spec"], source_date_field)
    target_dates = _fetch_side_date_column(target_kind, state["target_spec"], target_date_field)

    batches = plan_batches(source_dates, target_dates)
    if not batches:
        raise RuntimeError(
            "No parseable dates found on either side — cannot build a date-aligned "
            "batch plan (check the detected date fields "
            f"source={source_date_field!r}, target={target_date_field!r})."
        )
    pipeline_run_store.save_run_batch_plan(state["graph_run_id"], [b.to_dict() for b in batches])
    return {}


# ── step 5: run the streaming batch loop ─────────────────────────────────────

def _fetch_batch_dataset(
    kind: str,
    spec: dict[str, Any],
    date_filter: tuple[str, Any, Any],
    *,
    upload_frame: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if kind == "s4":
        return S4MetadataService().fetch_joined_dataset(spec, date_filter=date_filter)
    if kind == "ibp":
        field, start, end = date_filter
        return IBPMetadataService().fetch_entity(spec["entity"], spec["selected"], date_filter=(field, start, end))
    if kind == "upload":
        # Already fully local — "fetching" a batch means slicing the whole
        # (once-loaded, once-parsed) frame by this batch's date window rather
        # than issuing a live call. upload_frame/its parsed dates are
        # preloaded by _do_run_batches so this never re-reads the snapshot
        # from disk once per batch.
        field, start, end = date_filter
        df = upload_frame if upload_frame is not None else snapshot_store.load_snapshot_frame(spec["snapshot_id"])
        dates = parse_dates(df[field]).dt.normalize()
        mask = dates.notna() & (dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))
        return df[mask].reset_index(drop=True)
    raise RuntimeError(f"No batch fetcher for connector kind {kind!r}.")


def _pair_field_for_batch(
    *,
    graph_run_id: str,
    source_field: str,
    target_field: str,
    source_series: pd.Series,
    target_series: pd.Series,
    source_connector: str,
    target_connector: str,
    comparison_type: str,
    mapping_sheet_context: Any,
    source_dates: pd.Series,
    target_dates: pd.Series,
    actor: str,
    batch_label: str,
) -> ValueMapping:
    """One field pair's value-pairing for ONE date batch — reuses
    ``value_pairing.pipeline._pair_batch`` directly (library check + identity
    + LLM proposal/verification + template replay + resolve), but scoped to
    THIS BATCH's own target data (never the dataset-wide target — see
    ``_pair_batch``'s docstring on why that's safe specifically here: date is
    a confirmed, reliable part of the business key, and both sides are
    windowed together by the same date-union batch).

    Corroboration is accumulated incrementally: any match with competing
    ``sibling_candidates`` gets its within-batch evidence folded into
    ``storage.corroboration_store`` and its ``corroboration`` field
    overwritten with the cross-batch accumulated signal before returning.

    Every match also gets a deterministic ``pair_id`` (see ``recon_engine.
    ids.pair_id``) stamped on, and the returned ``ValueMapping`` its
    ``field_mapping_id`` — the identity a result row later points back at
    (see ``_do_run_batches``/``engine.executor``) to answer "why did this row
    match/miss" by lookup rather than investigation.
    """
    fm_id = ids.field_mapping_id(source_connector, target_connector, comparison_type, source_field, target_field)
    source_counts = distinct_values(source_series)
    target_values = set(distinct_values(target_series))
    matches, all_failed = _pair_batch(
        source_counts=source_counts,
        target_values=target_values,
        source_field=source_field,
        target_field=target_field,
        source_series=source_series,
        target_series=target_series,
        source_connector=source_connector,
        target_connector=target_connector,
        mapping_sheet_context=mapping_sheet_context,
        source_dates=source_dates,
        target_dates=target_dates,
        actor=actor,
        batch_label=batch_label,
    )
    if all_failed:
        raise Exception(  # noqa: TRY002 - mirrors ValuePairingUnavailable's hard-stop contract
            f"All configured AI providers are unavailable for value-pairing on "
            f"{source_field!r} -> {target_field!r} (batch {batch_label!r})."
        )

    accumulated: list[ValueMatch] = []
    for m in matches:
        if m.target_value is not None and m.candidates:
            source_seen, target_seen, overlap = corroboration_evidence(
                source_keys=source_series,
                source_dates=source_dates,
                source_value=m.source_value,
                target_keys=target_series,
                target_dates=target_dates,
                target_value=m.target_value,
            )
            corroboration_store.record_batch_evidence(
                graph_run_id,
                source_field=source_field,
                target_field=target_field,
                source_value=m.source_value,
                target_value=m.target_value,
                source_seen=source_seen,
                target_seen=target_seen,
                overlap=overlap,
            )
            cross_batch = corroboration_store.get_overlap(
                graph_run_id,
                source_field=source_field,
                target_field=target_field,
                source_value=m.source_value,
                target_value=m.target_value,
            )
            m = m.model_copy(update={"corroboration": cross_batch})
        m = m.model_copy(update={"pair_id": ids.pair_id(fm_id, m.source_value, m.target_value)})
        accumulated.append(m)

    return ValueMapping(
        source_field=source_field, target_field=target_field, field_mapping_id=fm_id, matches=accumulated
    )


def _do_run_batches(state: AutoRunState) -> dict[str, Any]:
    graph_run_id = state["graph_run_id"]
    plan = pipeline_run_store.get_run_batch_plan(graph_run_id)
    if not plan:
        raise RuntimeError("No date-batch plan found for this run — plan_date_batches must run first.")
    batches = [DateBatch.from_dict(b) for b in plan]
    batch_count = len(batches)

    contract = contract_store.get_contract(state["contract_id"], state["contract_version"])
    if contract is None or not contract.is_executable():
        raise RuntimeError(
            f"No approved, executable contract {state.get('contract_id')} "
            f"v{state.get('contract_version')} found."
        )

    checkpoint = pipeline_run_store.get_run_batch_checkpoint(graph_run_id)
    if checkpoint is not None:
        result_id = checkpoint["result_id"]
        start_index = checkpoint["next_batch_index"]
    else:
        result = result_store.start_streaming_result(
            run_id=graph_run_id, contract_id=contract.contract_id, contract_version=contract.contract_version
        )
        result_id = result.result_id
        start_index = 0

    source_kind = state["source"]["kind"]
    target_kind = state["target"]["kind"]
    source_spec = state["source_spec"]
    target_spec = state["target_spec"]
    source_roles = state["source_field_roles"]
    target_roles = state["target_field_roles"]
    source_connector = source_kind
    target_connector = target_kind
    comparison_type = state.get("comparison_type") or "auto"
    actor = state.get("actor", "auto")
    mapping_sheet_context = state.get("mapping_sheet")

    # An "upload" side is already fully local — load it once here rather
    # than once per batch (see _fetch_batch_dataset's upload_frame param).
    source_upload_frame = (
        snapshot_store.load_snapshot_frame(source_spec["snapshot_id"]) if source_kind == "upload" else None
    )
    target_upload_frame = (
        snapshot_store.load_snapshot_frame(target_spec["snapshot_id"]) if target_kind == "upload" else None
    )

    for batch in batches[start_index:]:
        # Cooperative-cancellation/-suspension checkpoint — between
        # date-batches, not mid-batch: each batch is already checkpointed on
        # completion, so stopping here never loses partial work (and, for
        # suspend, never leaves a half-resolved batch's value pairings
        # dangling — see value_pairing/pipeline.py's module docstring on why
        # every resolved pairing is already durable in the global library the
        # moment its batch completes). See _run_step's own top-of-node check
        # for the coarser (between-nodes) checkpoint. Cancel is checked first:
        # if both were somehow requested, a cancel wins (never park a run the
        # user asked to discard).
        if run_registry.is_cancelling(graph_run_id):
            return {"status": "cancelled", "result_id": result_id, "batch_count": batch_count}
        if run_registry.is_suspending(graph_run_id):
            return {"status": "suspended", "result_id": result_id, "batch_count": batch_count}

        # A fresh batch_id per ATTEMPT (never reused across a retry) — chained
        # to whatever attempt it replaces via supersedes_batch_id, so a failed
        # attempt's trail survives rather than being overwritten. Deterministic
        # pair_ids are unaffected either way (same pair -> same id regardless
        # of which attempt discovered it).
        prior_attempt = pipeline_run_store.get_latest_batch_attempt(graph_run_id, batch.batch_index)
        batch_id = ids.new_id()
        supersedes_batch_id = prior_attempt["batch_id"] if prior_attempt else None
        heartbeat.beat(graph_run_id, node="run_batches", batch_id=batch_id)

        try:
            pipeline_run_store.update_batch_progress(
                graph_run_id,
                field_pair=f"{source_roles['product']}/{source_roles['location']} -> "
                           f"{target_roles['product']}/{target_roles['location']}",
                batch_index=batch.batch_index,
                batch_count=batch.batch_count,
                batch_label=batch.label,
            )

            source_df = _fetch_batch_dataset(
                source_kind,
                source_spec,
                (source_roles["date"], batch.start_date, batch.end_date),
                upload_frame=source_upload_frame,
            )
            target_df = _fetch_batch_dataset(
                target_kind,
                target_spec,
                (target_roles["date"], batch.start_date, batch.end_date),
                upload_frame=target_upload_frame,
            )

            if source_df.empty and target_df.empty:
                pipeline_run_store.save_run_batch_checkpoint(
                    graph_run_id,
                    result_id=result_id,
                    next_batch_index=batch.batch_index + 1,
                    batch_count=batch_count,
                    summary=result_store.get_result(result_id).summary.model_dump(),
                )
                pipeline_run_store.record_batch_attempt(
                    graph_run_id,
                    batch_id=batch_id,
                    batch_index=batch.batch_index,
                    supersedes_batch_id=supersedes_batch_id,
                    status="completed",
                )
                continue

            source_dates = source_df[source_roles["date"]] if not source_df.empty else pd.Series([], dtype=object)
            target_dates = target_df[target_roles["date"]] if not target_df.empty else pd.Series([], dtype=object)

            set_llm_call_context(run_id=graph_run_id, batch_id=batch_id, node="run_batches")
            product_mapping = _pair_field_for_batch(
                graph_run_id=graph_run_id,
                source_field=source_roles["product"],
                target_field=target_roles["product"],
                source_series=source_df[source_roles["product"]] if not source_df.empty else pd.Series([], dtype=object),
                target_series=target_df[target_roles["product"]] if not target_df.empty else pd.Series([], dtype=object),
                source_connector=source_connector,
                target_connector=target_connector,
                comparison_type=comparison_type,
                mapping_sheet_context=mapping_sheet_context,
                source_dates=source_dates,
                target_dates=target_dates,
                actor=actor,
                batch_label=batch.label,
            )
            location_mapping = _pair_field_for_batch(
                graph_run_id=graph_run_id,
                source_field=source_roles["location"],
                target_field=target_roles["location"],
                source_series=source_df[source_roles["location"]] if not source_df.empty else pd.Series([], dtype=object),
                target_series=target_df[target_roles["location"]] if not target_df.empty else pd.Series([], dtype=object),
                source_connector=source_connector,
                target_connector=target_connector,
                comparison_type=comparison_type,
                mapping_sheet_context=mapping_sheet_context,
                source_dates=source_dates,
                target_dates=target_dates,
                actor=actor,
                batch_label=batch.label,
            )

            batch_contract = contract.model_copy(update={"value_mappings": [product_mapping, location_mapping]})
            built = build_shadow_source(batch_contract, source_df)
            recon = reconcile(batch_contract, built.shadow_df, target_df)
            recon.summary.excluded_unmapped = excluded_unmapped_counts(built.held_out)

            detail_df = recon.detail_df
            if not detail_df.empty:
                # Stamps every output row with what produced it — record_id is
                # fresh per row, run_id/batch_id are this attempt's (see
                # module docstring on why: any row must be traceable back to
                # its run + batch without investigation).
                detail_df = detail_df.copy()
                detail_df["run_id"] = graph_run_id
                detail_df["batch_id"] = batch_id
                detail_df["record_id"] = [ids.new_id() for _ in range(len(detail_df))]

            updated_result = result_store.append_batch_result(
                result_id, detail_df=detail_df, batch_summary=recon.summary
            )
            pipeline_run_store.save_run_batch_checkpoint(
                graph_run_id,
                result_id=result_id,
                next_batch_index=batch.batch_index + 1,
                batch_count=batch_count,
                summary=updated_result.summary.model_dump(),
            )
        except GraphBubbleUp:
            raise
        except Exception as exc:
            pipeline_run_store.record_batch_attempt(
                graph_run_id,
                batch_id=batch_id,
                batch_index=batch.batch_index,
                supersedes_batch_id=supersedes_batch_id,
                status="failed",
                error=str(exc),
            )
            raise
        else:
            pipeline_run_store.record_batch_attempt(
                graph_run_id,
                batch_id=batch_id,
                batch_index=batch.batch_index,
                supersedes_batch_id=supersedes_batch_id,
                status="completed",
            )
        finally:
            clear_llm_call_context()

    return {"result_id": result_id, "batch_count": batch_count}


# ── step 6: finalize ─────────────────────────────────────────────────────────

def _do_finalize(state: AutoRunState) -> dict[str, Any]:
    graph_run_id = state["graph_run_id"]
    result_id = state["result_id"]
    contract_id = state["contract_id"]
    contract_version = state["contract_version"]
    actor = state.get("actor", "auto")

    result = result_store.get_result(result_id)
    if result is None:
        raise RuntimeError(f"Streaming result {result_id!r} not found at finalize.")

    # A single ReconciliationRun row ties the streaming result back into the
    # existing runs/results UI surface. source_snapshot_id/target_snapshot_id
    # have no single dataset-wide equivalent under streaming (each batch is
    # its own small extract, never persisted as one combined snapshot), so
    # this run intentionally references the STREAMING RUN ITSELF, not a raw
    # snapshot — result_store/result detail rows remain the authoritative,
    # inspectable record of what was actually reconciled.
    run = ReconciliationRun(
        run_id=graph_run_id,
        contract_id=contract_id,
        contract_version=contract_version,
        source_snapshot_id=f"streaming:{graph_run_id}",
        target_snapshot_id=f"streaming:{graph_run_id}",
        status=RunStatus.COMPLETED,
        created_by=actor,
    )
    run_store.save_run(run)

    pipeline_run_store.clear_run_batch_state(graph_run_id)
    corroboration_store.clear(graph_run_id)

    contract = contract_store.get_contract(contract_id, contract_version)
    out: dict[str, Any] = {
        "run_id": run.run_id,
        "result_id": result.result_id,
        "summary": result.summary.model_dump(),
        "runtime_ms": None,
        "engine": "contract",
    }
    out["run"] = run.model_dump(mode="json")
    if contract is not None:
        out["contract"] = {
            "contract_id": contract.contract_id,
            "contract_version": contract.contract_version,
            "compiler": contract.compiler,
            "approved_by": contract.approved_by,
            "approved_at": contract.approved_at.isoformat() if contract.approved_at else None,
        }

    detail_df = result_store.load_result_frame_jsonl(result_id).head(200)
    preview_rows = (
        detail_df.astype(object).where(pd.notna(detail_df), None).to_dict(orient="records")
        if not detail_df.empty else []
    )
    out["detail"] = {"result": result.model_dump(mode="json"), "preview_rows": preview_rows}

    return {
        "contract_id": contract_id,
        "contract_version": contract_version,
        "run_id": run.run_id,
        "result_summary": out,
        "status": "completed",
    }


# ── per-node timing + hard-stop wrapper ──────────────────────────────────────

def _run_step(state: AutoRunState, step: str, fn: Callable[[AutoRunState], dict[str, Any]]) -> dict[str, Any]:
    timestamps = dict(state.get("step_timestamps") or {})
    graph_run_id = state.get("graph_run_id")

    # Cooperative-cancellation checkpoint — checked BEFORE this node does any
    # real work, so a CANCEL takes effect between nodes rather than only after
    # the whole run finishes. See run_registry.CooperativeCancellation for the
    # matching in-node checkpoint (run_batches' per-batch loop,
    # _make_batch_progress_cb's per-pair_values-batch callback).
    if graph_run_id and run_registry.is_cancelling(graph_run_id):
        now = time.time()
        timestamps[step] = {"start": now, "end": now}
        return {"step_timestamps": timestamps, "status": "cancelled", "failed_step": None, "error": None}

    if graph_run_id:
        heartbeat.beat(graph_run_id, node=step)

    start = time.time()
    set_llm_call_context(run_id=graph_run_id, node=step)
    try:
        updates = fn(state)
    except GraphBubbleUp:
        # A resolver's interrupt() (see interrupts.py) — must bubble straight
        # to LangGraph's runtime to pause/checkpoint the graph. Catching this
        # as a generic exception would silently convert a RECOVERABLE pause
        # into a hard "failed" status, and the resolver bot would never open.
        raise
    except CooperativeCancellation:
        # Raised from inside fn() (e.g. run_batches' per-batch loop, or
        # _make_batch_progress_cb's on_batch callback) once a cancel was
        # observed mid-node — a clean stop, not a failure: no error_event.
        timestamps[step] = {"start": start, "end": time.time()}
        return {"step_timestamps": timestamps, "status": "cancelled", "failed_step": None, "error": None}
    except CooperativeSuspension:
        # Mirrors CooperativeCancellation above — a clean, deliberate park,
        # not a failure: no error_event.
        timestamps[step] = {"start": start, "end": time.time()}
        return {"step_timestamps": timestamps, "status": "suspended", "failed_step": None, "error": None}
    except Exception as exc:  # noqa: BLE001 - any exception here is a genuine hard failure
        timestamps[step] = {"start": start, "end": time.time()}
        message = run_registry.format_failure(graph_run_id, step, detail=str(exc))
        # One error_event per hard node failure, across all 7 wizard steps —
        # a run_batches failure's batch-specific detail is already captured
        # by pipeline_run_store.record_batch_attempt (with the real batch_id),
        # so this is never duplicated with one here.
        error_event_store.record(run_id=graph_run_id, batch_id=None, node=step, message=str(exc))
        return {
            "step_timestamps": timestamps,
            "status": "failed",
            "failed_step": step,
            "error": message,
        }
    finally:
        clear_llm_call_context()
    timestamps[step] = {"start": start, "end": time.time()}
    result = dict(updates)
    result["step_timestamps"] = timestamps
    return result


def select_source(state: AutoRunState) -> dict[str, Any]:
    return _run_step(state, "select_source", _do_select_source)


def select_target(state: AutoRunState) -> dict[str, Any]:
    return _run_step(state, "select_target", _do_select_target)


def resolve_schema(state: AutoRunState) -> dict[str, Any]:
    return _run_step(state, "resolve_schema", _do_resolve_schema)


def compile_contract(state: AutoRunState) -> dict[str, Any]:
    return _run_step(state, "compile_contract", _do_compile_contract)


def plan_date_batches(state: AutoRunState) -> dict[str, Any]:
    return _run_step(state, "plan_date_batches", _do_plan_date_batches)


def run_batches(state: AutoRunState) -> dict[str, Any]:
    return _run_step(state, "run_batches", _do_run_batches)


def finalize(state: AutoRunState) -> dict[str, Any]:
    return _run_step(state, "finalize", _do_finalize)
