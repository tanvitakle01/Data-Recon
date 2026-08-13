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
"""

from __future__ import annotations

import time
from typing import Any, Callable

import pandas as pd
from langgraph.errors import GraphBubbleUp

from backend.API_conn.connectors import registry
from backend.API_conn.connectors.ibp_metadata_service import IBPMetadataService
from backend.API_conn.connectors.s4_metadata_service import S4MetadataService
from backend.recon_engine import service
from backend.recon_engine.models.snapshot import RawLayer
from backend.recon_engine.storage import (
    contract_store,
    pipeline_run_store,
    result_store,
    run_store,
    snapshot_store,
)
from backend.recon_engine.value_pairing import BatchProgress, pair_values
from backend.recon_engine.value_pairing.extraction import distinct_values

from backend.recon_engine.auto_pipeline.candidate_keys import identify_candidate_keys
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


# ── step 1/3: select connector/entity ────────────────────────────────────────

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
    return {"source": _select_side(state["identification"]["source"], registry.SOURCE)}


def _do_select_target(state: AutoRunState) -> dict[str, Any]:
    return {"target": _select_side(state["identification"]["target"], registry.TARGET)}


# ── step 2/4: import data ─────────────────────────────────────────────────────

def _live_property_names(client: S4MetadataService, entity: str) -> list[str]:
    return [p["name"] for p in client.get_entity_properties(entity)]


def _fetch_s4_dataset(side: SideState, role: str) -> tuple[pd.DataFrame, dict[str, Any]]:
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
    df = client.fetch_joined_dataset(spec)
    return df, {"primary_entity": primary, "entities": [primary, *joined_entities]}


def _fetch_ibp_dataset(side: SideState, role: str) -> tuple[pd.DataFrame, dict[str, Any]]:
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
    df = client.fetch_entity(primary, matched)
    return df, {"primary_entity": primary}


_FETCHERS: dict[str, Callable[[SideState, str], tuple[pd.DataFrame, dict[str, Any]]]] = {
    "s4": _fetch_s4_dataset,
    "ibp": _fetch_ibp_dataset,
}


def _import_side(state: AutoRunState, role: str, layer: RawLayer) -> dict[str, Any]:
    side = state[role]
    fetcher = _FETCHERS.get(side["kind"])
    if fetcher is None:
        raise RuntimeError(f"No live-fetch importer for connector kind {side['kind']!r}.")
    df, resolved = fetcher(side, role)
    if df is None or df.empty:
        raise RuntimeError(
            f"{role.capitalize()} import returned no rows "
            f"(entity={resolved.get('primary_entity', side['primary_entity'])!r})."
        )
    updated = dict(side)
    updated.update(resolved)
    snap = service.ingest_snapshot(
        df,
        layer=layer,
        source_type=side["kind"],
        comparison_type=state.get("comparison_type"),
        created_by=state.get("actor", "system"),
        lineage={"graph_run_id": state["graph_run_id"], "entity": updated["primary_entity"]},
    )
    updated["snapshot_id"] = snap.snapshot_id
    updated["row_count"] = snap.row_count
    updated["columns"] = list(snap.columns)
    return {role: updated}


def _do_import_source(state: AutoRunState) -> dict[str, Any]:
    return _import_side(state, "source", RawLayer.SOURCE)


def _do_import_target(state: AutoRunState) -> dict[str, Any]:
    return _import_side(state, "target", RawLayer.TARGET)


# ── step 5: Stage 3 (LLM ONLY) — candidate business-key identification ──────

def _do_identify_candidate_keys(state: AutoRunState) -> dict[str, Any]:
    """Identify the product/location candidate keys for value pairing (LLM).

    Used EXCLUSIVELY to drive value pairing (extract_unique_keys/pair_values)
    below — never fed into ``business_key`` (see compile_and_run), which stays
    a separate, deterministic concept sourced from date/quantity role
    detection. Hard-stops on degradation: Auto mode has no human checkpoint to
    catch a silently-skipped LLM stage the way Manual mode's approval step
    would.
    """
    source_df = snapshot_store.load_snapshot_frame(state["source"]["snapshot_id"])
    target_df = snapshot_store.load_snapshot_frame(state["target"]["snapshot_id"])
    result = identify_candidate_keys(
        [str(c) for c in source_df.columns],
        [str(c) for c in target_df.columns],
        mapping_sheet_context=state.get("mapping_sheet"),
    )
    if result.get("degraded"):
        raise RuntimeError(
            f"Candidate-key identification failed: {result.get('degraded_reason')}"
        )
    missing = [
        f"{side}.{role}"
        for side in ("source", "target")
        for role in _CANDIDATE_KEY_ROLES
        if not result[side][role]["field"]
    ]
    if missing:
        raise RuntimeError(
            f"Could not identify a candidate key for {missing} from the fetched "
            f"columns (source={list(source_df.columns)!r}, "
            f"target={list(target_df.columns)!r})."
        )
    return {"candidate_keys": result}


# ── step 6: identify unique key values ───────────────────────────────────────

def _do_extract_unique_keys(state: AutoRunState) -> dict[str, Any]:
    source_df = snapshot_store.load_snapshot_frame(state["source"]["snapshot_id"])
    # Which column plays the product/location role is the Stage-3 LLM's
    # candidate-key output (never a hardcoded literal, never alias-detected) —
    # see identify_candidate_keys_step.
    candidate_keys = state["candidate_keys"]["source"]
    product_field = candidate_keys["product"]["field"]
    location_field = candidate_keys["location"]["field"]
    return {
        "unique_values": {
            "source_product": distinct_values(source_df[product_field]),
            "source_location": distinct_values(source_df[location_field]),
        }
    }


# ── step 6: LLM value-pairing + mandatory verification ───────────────────────

def _make_batch_progress_cb(graph_run_id: str) -> Any:
    """Live "batch N of M (label)" progress for the Auto-mode process card —
    pair_values() calls this after every year-range batch resolves, for both
    the product and location pairing calls below (a fresh closure per call,
    so the polled status always reflects whichever field pair is currently
    mid-flight rather than stale progress from the other one).
    """

    def _on_batch(progress: BatchProgress) -> None:
        pipeline_run_store.update_batch_progress(
            graph_run_id,
            field_pair=progress.field_pair,
            batch_index=progress.batch_index,
            batch_count=progress.batch_count,
            batch_label=progress.batch_label,
        )

    return _on_batch


def _do_pair_values(state: AutoRunState) -> dict[str, Any]:
    source_df = snapshot_store.load_snapshot_frame(state["source"]["snapshot_id"])
    target_df = snapshot_store.load_snapshot_frame(state["target"]["snapshot_id"])

    # product/location: the Stage-3 LLM's candidate-key output (identify_
    # candidate_keys_step), already hard-validated by that node — used
    # EXCLUSIVELY here to drive value pairing.
    candidate_keys = state["candidate_keys"]
    source_roles = {role: candidate_keys["source"][role]["field"] for role in _CANDIDATE_KEY_ROLES}
    target_roles = {role: candidate_keys["target"][role]["field"] for role in _CANDIDATE_KEY_ROLES}

    # date/quantity: a SEPARATE, deterministic, alias-based detection — never
    # the LLM candidate keys above. Used only for the corroboration-date
    # signal here, and later (independently) for business_key/compare_fields
    # in compile_and_run — the two concepts never share a mechanism.
    source_bkey_roles = detect_roles_for_columns([str(c) for c in source_df.columns])
    target_bkey_roles = detect_roles_for_columns([str(c) for c in target_df.columns])
    missing_source = [r for r in _BUSINESS_KEY_ROLES if r not in source_bkey_roles]
    missing_target = [r for r in _BUSINESS_KEY_ROLES if r not in target_bkey_roles]
    if missing_source or missing_target:
        raise RuntimeError(
            "Could not detect all required business-key roles (date/quantity) for "
            f"reconciliation — source missing {missing_source or 'none'} "
            f"(columns: {list(source_df.columns)!r}), target missing "
            f"{missing_target or 'none'} (columns: {list(target_df.columns)!r})."
        )
    source_roles.update({role: source_bkey_roles[role] for role in _BUSINESS_KEY_ROLES})
    target_roles.update({role: target_bkey_roles[role] for role in _BUSINESS_KEY_ROLES})

    source_dates = source_df[source_roles["date"]]
    target_dates = target_df[target_roles["date"]]
    source_connector = state["source"]["kind"]
    target_connector = state["target"]["kind"]
    actor = state.get("actor", "auto")
    mapping_sheet_context = state.get("mapping_sheet")
    graph_run_id = state["graph_run_id"]

    # raise_on_batch_failure=True: Auto mode has no human checkpoint to catch
    # a silently-degraded batch the way Manual mode's review step would, so a
    # batch whose LLM calls fail on every configured provider (even after
    # pair_values' own bounded retry) hard-stops here instead of degrading —
    # see ValuePairingUnavailable.
    product = pair_values(
        source_field=source_roles["product"],
        target_field=target_roles["product"],
        source_series=source_df[source_roles["product"]],
        target_series=target_df[target_roles["product"]],
        source_connector=source_connector,
        target_connector=target_connector,
        mapping_sheet_context=mapping_sheet_context,
        source_dates=source_dates,
        target_dates=target_dates,
        actor=actor,
        raise_on_batch_failure=True,
        on_batch=_make_batch_progress_cb(graph_run_id),
    )
    location = pair_values(
        source_field=source_roles["location"],
        target_field=target_roles["location"],
        source_series=source_df[source_roles["location"]],
        target_series=target_df[target_roles["location"]],
        source_connector=source_connector,
        target_connector=target_connector,
        mapping_sheet_context=mapping_sheet_context,
        source_dates=source_dates,
        target_dates=target_dates,
        actor=actor,
        raise_on_batch_failure=True,
        on_batch=_make_batch_progress_cb(graph_run_id),
    )

    return {
        "product_mapping": product.model_dump(mode="json"),
        "location_mapping": location.model_dump(mode="json"),
        "source_field_roles": source_roles,
        "target_field_roles": target_roles,
    }


# ── step 7: compile, approve, run ─────────────────────────────────────────────

def _do_compile_and_run(state: AutoRunState) -> dict[str, Any]:
    source_snap_id = state["source"]["snapshot_id"]
    target_snap_id = state["target"]["snapshot_id"]
    source_df = snapshot_store.load_snapshot_frame(source_snap_id)
    target_df = snapshot_store.load_snapshot_frame(target_snap_id)
    actor = state.get("actor", "auto")

    # Reuse the exact roles pair_values_step already detected and validated —
    # never a fresh hardcoded assumption, and guarantees business_key/
    # compare_fields agree with whatever was actually paired.
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
    value_mappings = [m for m in (state.get("product_mapping"), state.get("location_mapping")) if m]

    draft, degraded_reason = service.compile_draft(
        mapping_sheet=state.get("mapping_sheet") or [],
        rules="",
        business_key=business_key,
        compare_fields=compare_fields,
        value_mappings=value_mappings,
        source_schema=[str(c) for c in source_df.columns],
        target_schema=[str(c) for c in target_df.columns],
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

    started = time.time()
    out = service.run_reconciliation(
        contract_id=approved.contract_id,
        contract_version=approved.contract_version,
        source_snapshot_id=source_snap_id,
        target_snapshot_id=target_snap_id,
        actor=actor,
    )
    # Mirror the exact enrichment recon_v2.py's `POST /api/recon/runs` route
    # adds (contract/snapshot summaries) plus the result detail `GET
    # /api/recon/results/{id}` returns, so the frontend can drop this straight
    # into `reconciliation` state and render Results identically to a manual
    # contract run — no extra API round-trips needed after landing.
    out["runtime_ms"] = int((time.time() - started) * 1000)
    run = run_store.get_run(out["run_id"])
    if run is not None:
        out["run"] = run.model_dump(mode="json")
        run_contract = contract_store.get_contract(run.contract_id, run.contract_version)
        if run_contract is not None:
            out["contract"] = {
                "contract_id": run_contract.contract_id,
                "contract_version": run_contract.contract_version,
                "compiler": run_contract.compiler,
                "approved_by": run_contract.approved_by,
                "approved_at": run_contract.approved_at.isoformat() if run_contract.approved_at else None,
            }
    for key, snap_id in (("source_snapshot", source_snap_id), ("target_snapshot", target_snap_id)):
        snap = snapshot_store.get_snapshot(snap_id)
        if snap is not None:
            out[key] = snap.model_dump(mode="json")

    result_row = result_store.get_result(out["result_id"])
    preview_rows: list[dict[str, Any]] = []
    if result_row is not None:
        detail_df = result_store.load_result_frame(out["result_id"]).head(200)
        preview_rows = detail_df.astype(object).where(pd.notna(detail_df), None).to_dict(orient="records")
    out["detail"] = {
        "result": result_row.model_dump(mode="json") if result_row else None,
        "preview_rows": preview_rows,
    }
    out["engine"] = "contract"

    return {
        "contract_id": approved.contract_id,
        "contract_version": approved.contract_version,
        "run_id": out["run_id"],
        "result_summary": out,
        "status": "completed",
    }


# ── per-node timing + hard-stop wrapper ──────────────────────────────────────

def _run_step(state: AutoRunState, step: str, fn: Callable[[AutoRunState], dict[str, Any]]) -> dict[str, Any]:
    start = time.time()
    timestamps = dict(state.get("step_timestamps") or {})
    try:
        updates = fn(state)
    except GraphBubbleUp:
        # A resolver's interrupt() (see interrupts.py) — must bubble straight
        # to LangGraph's runtime to pause/checkpoint the graph. Catching this
        # as a generic exception would silently convert a RECOVERABLE pause
        # into a hard "failed" status, and the resolver bot would never open.
        raise
    except Exception as exc:  # noqa: BLE001 - any exception here is a genuine hard failure
        timestamps[step] = {"start": start, "end": time.time()}
        return {
            "step_timestamps": timestamps,
            "status": "failed",
            "failed_step": step,
            "error": str(exc),
        }
    timestamps[step] = {"start": start, "end": time.time()}
    result = dict(updates)
    result["step_timestamps"] = timestamps
    return result


def select_source(state: AutoRunState) -> dict[str, Any]:
    return _run_step(state, "select_source", _do_select_source)


def import_source(state: AutoRunState) -> dict[str, Any]:
    return _run_step(state, "import_source", _do_import_source)


def select_target(state: AutoRunState) -> dict[str, Any]:
    return _run_step(state, "select_target", _do_select_target)


def import_target(state: AutoRunState) -> dict[str, Any]:
    return _run_step(state, "import_target", _do_import_target)


def identify_candidate_keys_step(state: AutoRunState) -> dict[str, Any]:
    return _run_step(state, "identify_candidate_keys", _do_identify_candidate_keys)


def extract_unique_keys(state: AutoRunState) -> dict[str, Any]:
    return _run_step(state, "extract_unique_keys", _do_extract_unique_keys)


def pair_values_step(state: AutoRunState) -> dict[str, Any]:
    return _run_step(state, "pair_values", _do_pair_values)


def compile_and_run(state: AutoRunState) -> dict[str, Any]:
    return _run_step(state, "compile_and_run", _do_compile_and_run)
