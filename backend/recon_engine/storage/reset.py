"""Test-support helper: clear every in-memory store.

Stage-1 has no DB to isolate per test with a temp directory — each store
module holds its state in module-level dicts instead. This just empties all
of them, so tests remain isolated from each other.
"""

from __future__ import annotations

from backend.recon_engine.storage import (
    attribute_mapping_store,
    audit_store,
    contract_store,
    frames,
    llm_call_store,
    result_store,
    run_store,
    run_value_mapping_store,
    script_store,
    shadow_store,
    snapshot_store,
    value_pair_store,
)


def reset_all() -> None:
    snapshot_store._SNAPSHOTS.clear()
    contract_store._CONTRACTS.clear()
    run_store._RUNS.clear()
    audit_store._EVENTS.clear()
    result_store._RESULTS.clear()
    shadow_store._SHADOWS.clear()
    llm_call_store._CALLS.clear()
    script_store._SCRIPTS.clear()
    script_store._PREVIEWS.clear()
    script_store._APPROVALS.clear()
    run_value_mapping_store._RUN_MATCHES.clear()
    run_value_mapping_store._BATCH_MATCHES.clear()
    value_pair_store._PAIRS.clear()
    value_pair_store._STATUS.clear()
    value_pair_store._RUN_SCOPE.clear()
    attribute_mapping_store._MAPPINGS.clear()
    frames._FRAME_STORE.clear()
