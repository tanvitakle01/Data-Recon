"""Durable persistence layer (SQLite + on-disk frames).

Replaces the previous in-memory-only ``_FILE_STORE`` design. Submodules:

* ``db``             — connections + schema init (recon.db, recon_shadow.db)
* ``frames``         — DataFrame (de)serialization + content hashing
* ``snapshot_store`` — immutable, append-only raw snapshots
* ``contract_store`` — versioned contracts
* ``run_store``      — reconciliation runs
* ``shadow_store``   — Shadow_Source (recon_shadow schema) with TTL cleanup
* ``result_store``   — reconciliation results
* ``audit_store``    — append-only audit log
* ``script_store``   — transformation scripts, preview snapshots, approvals
"""

from backend.recon_engine.storage.db import init_storage

__all__ = ["init_storage"]
