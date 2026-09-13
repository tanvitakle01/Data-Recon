"""In-memory persistence layer (no DB, no disk state).

Everything here lives only in process memory for the lifetime of the running
server — a restart loses it, which is correct for a stateless Stage-1
deployment. Submodules:

* ``frames``                 — DataFrame storage + content hashing
* ``snapshot_store``         — immutable, append-only raw snapshots
* ``contract_store``         — versioned contracts
* ``run_store``               — reconciliation runs
* ``shadow_store``            — Shadow_Source with TTL cleanup
* ``result_store``            — reconciliation results
* ``audit_store``             — append-only audit log
* ``script_store``            — transformation scripts, preview snapshots, approvals
* ``attribute_mapping_store`` — field-mapping reuse library
* ``value_pair_store``        — value-pairing reuse library
* ``llm_call_store``          — LLM call log
* ``run_value_mapping_store`` — per-run value-mapping accumulator
"""
