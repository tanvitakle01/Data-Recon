"""``pair_values`` for the chat/"from data" Auto-mode graph — identical to
``nodes.py``'s ``_do_pair_values`` except business-key role detection
(date/quantity) is LLM-based (see ``business_key_roles.py``) instead of the
live-connector path's deterministic alias matching, which real-world
chat-uploaded files routinely miss (abbreviated/inconsistent headers like
``Req.Dlv.Dt``, ``KEYFIGUREDATE``). Everything else — candidate-key roles,
value pairing itself, batch progress — is the exact same call into
``value_pairing.pair_values``, never reimplemented.

``compile_and_run`` needs no from-data variant: it only reads
``state["source_field_roles"]``/``["target_field_roles"]`` (set by whichever
pair_values ran) and never detects roles itself — see ``graph_from_data.py``,
which reuses ``nodes.compile_and_run`` unchanged.
"""

from __future__ import annotations

from typing import Any

from backend.recon_engine.auto_pipeline.business_key_roles import identify_business_key_roles
from backend.recon_engine.auto_pipeline.nodes import (
    _CANDIDATE_KEY_ROLES,
    _make_batch_progress_cb,
    _resume_state_for,
    _run_step,
)
from backend.recon_engine.auto_pipeline.state import AutoRunState
from backend.recon_engine.storage import pipeline_run_store, snapshot_store
from backend.recon_engine.value_pairing import pair_values

_SAMPLE_ROW_COUNT = 3


def _sample_rows(df, limit: int = _SAMPLE_ROW_COUNT) -> list[dict[str, Any]]:
    head = df.head(limit)
    return head.astype(object).where(head.notna(), None).to_dict(orient="records")


def _do_pair_values_from_data(state: AutoRunState) -> dict[str, Any]:
    source_df = snapshot_store.load_snapshot_frame(state["source"]["snapshot_id"])
    target_df = snapshot_store.load_snapshot_frame(state["target"]["snapshot_id"])

    # product/location: the same Stage-3 LLM candidate-key output every
    # Auto-mode path uses — unchanged from nodes.py's _do_pair_values.
    candidate_keys = state["candidate_keys"]
    source_roles = {role: candidate_keys["source"][role]["field"] for role in _CANDIDATE_KEY_ROLES}
    target_roles = {role: candidate_keys["target"][role]["field"] for role in _CANDIDATE_KEY_ROLES}

    # date/quantity: LLM-based, using column names AND real sample rows as
    # evidence — the "from data" path's replacement for the live-connector
    # path's fixed alias list (see module docstring).
    role_result = identify_business_key_roles(
        [str(c) for c in source_df.columns],
        [str(c) for c in target_df.columns],
        _sample_rows(source_df),
        _sample_rows(target_df),
        mapping_sheet_context=state.get("mapping_sheet"),
    )
    if role_result.get("degraded"):
        raise RuntimeError(
            f"Business-key role identification failed: {role_result.get('degraded_reason')}"
        )
    source_bkey_roles = {
        role: role_result["source"][role]["field"]
        for role in ("date", "quantity")
        if role_result["source"][role]["field"]
    }
    target_bkey_roles = {
        role: role_result["target"][role]["field"]
        for role in ("date", "quantity")
        if role_result["target"][role]["field"]
    }
    missing_source = [r for r in ("date", "quantity") if r not in source_bkey_roles]
    missing_target = [r for r in ("date", "quantity") if r not in target_bkey_roles]
    if missing_source or missing_target:
        raise RuntimeError(
            "Could not identify all required business-key roles (date/quantity) for "
            f"reconciliation — source missing {missing_source or 'none'} "
            f"(columns: {list(source_df.columns)!r}), target missing "
            f"{missing_target or 'none'} (columns: {list(target_df.columns)!r})."
        )
    source_roles.update(source_bkey_roles)
    target_roles.update(target_bkey_roles)

    source_dates = source_df[source_roles["date"]]
    target_dates = target_df[target_roles["date"]]
    source_connector = state["source"]["kind"]
    target_connector = state["target"]["kind"]
    actor = state.get("actor", "auto")
    mapping_sheet_context = state.get("mapping_sheet")
    graph_run_id = state["graph_run_id"]

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
        **_resume_state_for(graph_run_id, source_roles["product"], target_roles["product"]),
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
        **_resume_state_for(graph_run_id, source_roles["location"], target_roles["location"]),
    )

    pipeline_run_store.clear_batch_checkpoints(graph_run_id)

    return {
        "product_mapping": product.model_dump(mode="json"),
        "location_mapping": location.model_dump(mode="json"),
        "source_field_roles": source_roles,
        "target_field_roles": target_roles,
    }


def pair_values_step_from_data(state: AutoRunState) -> dict[str, Any]:
    return _run_step(state, "pair_values", _do_pair_values_from_data)
