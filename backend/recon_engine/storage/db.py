"""SQLite persistence foundation.

Two database files are used to emulate schema boundaries:

* ``recon.db``        — the authoritative metadata store: raw snapshots,
                        contracts (versioned), runs, results, audit log.
* ``recon_shadow.db`` — the ``recon_shadow`` schema: derived, disposable
                        Shadow_Source metadata governed by a TTL.

Row *data* (raw snapshots, shadow frames, result details) is written to
parquet files on disk; these tables hold metadata + lineage and point at the
files. This replaces the previous in-memory-only ``_FILE_STORE`` design with a
durable, restart-surviving store.

Immutability of the raw layer is enforced structurally: the snapshot store
exposes no update/delete; snapshot tables are append-only by construction.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from backend.recon_engine.config import get_settings

logger = logging.getLogger("recon.storage.db")

# ── DDL ───────────────────────────────────────────────────────────────────────

_MAIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_snapshots (
    snapshot_id     TEXT PRIMARY KEY,
    layer           TEXT NOT NULL,
    source_type     TEXT NOT NULL,
    comparison_type TEXT,
    snapshot_hash   TEXT NOT NULL,
    row_count       INTEGER NOT NULL,
    columns_json    TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    created_by      TEXT NOT NULL,
    storage_path    TEXT NOT NULL,
    lineage_json    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contracts (
    contract_id       TEXT NOT NULL,
    contract_version  INTEGER NOT NULL,
    comparison_type   TEXT NOT NULL,
    source_type       TEXT NOT NULL,
    target_type       TEXT NOT NULL,
    approval_status   TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    created_by        TEXT NOT NULL,
    approved_at       TEXT,
    approved_by       TEXT,
    compiler          TEXT NOT NULL,
    body_json         TEXT NOT NULL,
    PRIMARY KEY (contract_id, contract_version)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id             TEXT PRIMARY KEY,
    contract_id        TEXT NOT NULL,
    contract_version   INTEGER NOT NULL,
    source_snapshot_id TEXT NOT NULL,
    target_snapshot_id TEXT NOT NULL,
    shadow_id          TEXT,
    status             TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    created_by         TEXT NOT NULL,
    error              TEXT
);

CREATE TABLE IF NOT EXISTS results (
    result_id        TEXT PRIMARY KEY,
    run_id           TEXT NOT NULL,
    contract_id      TEXT NOT NULL,
    contract_version INTEGER NOT NULL,
    summary_json     TEXT NOT NULL,
    storage_path     TEXT NOT NULL,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    event_id    TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    details_json TEXT NOT NULL
);

-- Script-transformation flow (USE_SCRIPT_TRANSFORMATIONS): generated scripts
-- are internal artifacts pinned by hash; users approve preview DATA, and the
-- approval binds preview -> script hash for production execution.
CREATE TABLE IF NOT EXISTS transformation_scripts (
    script_id           TEXT PRIMARY KEY,
    generated_by        TEXT NOT NULL,
    generated_at        TEXT NOT NULL,
    explanation_json    TEXT NOT NULL,
    script_text         TEXT NOT NULL,
    script_hash         TEXT NOT NULL,
    source_columns_json TEXT NOT NULL,
    target_columns_json TEXT NOT NULL,
    confidence          REAL NOT NULL,
    validation_ok       INTEGER NOT NULL,
    validation_json     TEXT NOT NULL,
    created_by          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS script_previews (
    preview_id            TEXT PRIMARY KEY,
    script_id             TEXT NOT NULL,
    script_hash           TEXT NOT NULL,
    row_count             INTEGER NOT NULL,
    affected_rows         INTEGER NOT NULL,
    modified_columns_json TEXT NOT NULL,
    row_diffs_json        TEXT NOT NULL,
    execution_log_json    TEXT NOT NULL,
    storage_path          TEXT NOT NULL,
    status                TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    created_by            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS script_approvals (
    approval_id         TEXT PRIMARY KEY,
    preview_snapshot_id TEXT NOT NULL,
    script_id           TEXT NOT NULL,
    script_hash         TEXT NOT NULL,
    approved_by         TEXT NOT NULL,
    approved_at         TEXT NOT NULL
);

-- Attribute-mapping library: a reconciled FIELD (column→column) mapping stored
-- so the identical source+target column set reappearing is answered from here
-- instead of the LLM. The UNIQUE constraint is the canonical dedup key — the
-- two *_columns_key values are order-independent SHA-256 hashes (see
-- recon_engine.canonical). Field mapping only; never value mapping.
CREATE TABLE IF NOT EXISTS attribute_mappings (
    id                  TEXT PRIMARY KEY,
    source_connector    TEXT NOT NULL,
    target_connector    TEXT NOT NULL,
    comparison_type     TEXT NOT NULL,
    source_columns_key  TEXT NOT NULL,
    target_columns_key  TEXT NOT NULL,
    mappings_json       TEXT NOT NULL,
    provenance          TEXT NOT NULL,
    confidence          REAL,
    added_by            TEXT NOT NULL,
    added_on            TEXT NOT NULL,
    last_used_on        TEXT,
    validated_by_run_id TEXT,
    version             INTEGER NOT NULL,
    details_json        TEXT NOT NULL,
    UNIQUE (source_connector, target_connector, comparison_type,
            source_columns_key, target_columns_key)
);

-- Auto-mode pipeline runs: tracks ONE end-to-end Auto-mode graph execution
-- across all 7 wizard steps (mapping-sheet identify through reconciliation),
-- distinct from `runs` (ReconciliationRun), which only ever covers step 7's
-- execution of an already-approved contract. Polled by the frontend for the
-- elapsed-time display and terminal status.
CREATE TABLE IF NOT EXISTS pipeline_runs (
    graph_run_id        TEXT PRIMARY KEY,
    status              TEXT NOT NULL,
    current_step        TEXT,
    step_timestamps_json TEXT NOT NULL,
    failed_step         TEXT,
    error               TEXT,
    result_json         TEXT,
    created_at          TEXT NOT NULL,
    batch_progress_json TEXT,
    interrupt_json      TEXT
);

-- Batch-level checkpoint for one field pair's pair_values() call within an
-- Auto-mode `pair_values` node, keyed by (graph_run_id, field_pair) — e.g.
-- ("autorun_ab12", "Material -> PRDID"). Written after every batch that
-- resolves successfully (see auto_pipeline/nodes.py's _make_batch_progress_cb)
-- so a batch that later fails (ValuePairingUnavailable) can be retried from
-- exactly next_batch_index instead of redoing the whole field pair — see
-- auto_pipeline/graph.py's retry_auto_pipeline. Cleared once the owning
-- `pair_values` node completes successfully for both field pairs.
CREATE TABLE IF NOT EXISTS pipeline_batch_checkpoints (
    graph_run_id      TEXT NOT NULL,
    field_pair        TEXT NOT NULL,
    next_batch_index  INTEGER NOT NULL,
    batch_count       INTEGER NOT NULL,
    matches_json      TEXT NOT NULL,
    PRIMARY KEY (graph_run_id, field_pair)
);

-- Value-pair library: a source_value -> target_value pairing for one Key
-- field pair (e.g. Material -> PRDID), discovered by the LLM-pairing pipeline
-- and deterministically verified before it is ever stored here. Every stored
-- row is consulted by the pipeline's library-first lookup — persisted
-- automatically, no review step. Field mapping never lives here.
CREATE TABLE IF NOT EXISTS value_pair_library (
    id                  TEXT PRIMARY KEY,
    source_connector    TEXT NOT NULL,
    target_connector    TEXT NOT NULL,
    source_field        TEXT NOT NULL,
    target_field        TEXT NOT NULL,
    source_value        TEXT NOT NULL,
    target_value        TEXT NOT NULL,
    ops_json            TEXT NOT NULL,
    evidence_json       TEXT NOT NULL,
    added_by            TEXT NOT NULL,
    added_on            TEXT NOT NULL,
    version             INTEGER NOT NULL,
    UNIQUE (source_connector, target_connector, source_field, target_field,
            source_value, target_value)
);
"""

_SHADOW_SCHEMA = """
CREATE TABLE IF NOT EXISTS shadow_sources (
    shadow_id          TEXT PRIMARY KEY,
    run_id             TEXT NOT NULL,
    contract_id        TEXT NOT NULL,
    contract_version   INTEGER NOT NULL,
    raw_snapshot_id    TEXT NOT NULL,
    raw_snapshot_hash  TEXT NOT NULL,
    row_count          INTEGER NOT NULL,
    storage_path       TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    expires_at         TEXT NOT NULL
);
"""


def _connect(path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _migrate_value_pair_library(conn: sqlite3.Connection) -> None:
    """One-time migration for a database predating the single-op -> ordered-
    chain refactor.

    The value-pairing pipeline used to store one ``op`` + ``params_json`` per
    row; it now stores an ORDERED CHAIN as a single ``ops_json`` array (see
    ``storage.value_pair_store``). ``CREATE TABLE IF NOT EXISTS`` never alters
    an existing table, so a store created before this change keeps its old
    columns and lacks ``ops_json`` forever — every insert then fails with
    "table value_pair_library has no column named ops_json". Rebuilds the
    table (works on any SQLite version, unlike ``ALTER TABLE ... DROP
    COLUMN``) rather than just adding ``ops_json`` alongside the legacy
    columns, which would leave their NOT NULL constraints in place and break
    every future insert (the current INSERT never populates them).
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(value_pair_library)")}
    if not cols or "ops_json" in cols:
        return  # table doesn't exist yet, or already on the current schema
    if "op" not in cols or "params_json" not in cols:
        return  # unrecognized shape - nothing safe to migrate automatically

    conn.execute("ALTER TABLE value_pair_library RENAME TO value_pair_library_old")
    conn.executescript(_MAIN_SCHEMA)  # recreates value_pair_library on the current DDL

    rows = conn.execute("SELECT * FROM value_pair_library_old").fetchall()
    for row in rows:
        params = json.loads(row["params_json"]) if row["params_json"] else {}
        ops_json = json.dumps([{"op": row["op"], "params": params}])
        conn.execute(
            """INSERT INTO value_pair_library
               (id, source_connector, target_connector, source_field, target_field,
                source_value, target_value, ops_json, evidence_json,
                added_by, added_on, version)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["id"], row["source_connector"], row["target_connector"],
                row["source_field"], row["target_field"], row["source_value"],
                row["target_value"], ops_json, row["evidence_json"],
                row["added_by"], row["added_on"], row["version"],
            ),
        )
    conn.execute("DROP TABLE value_pair_library_old")
    logger.info(
        "Migrated value_pair_library: %d row(s) moved from legacy (op, params_json) to ops_json.",
        len(rows),
    )


def _migrate_value_pair_library_target_value(conn: sqlite3.Connection) -> None:
    """One-time migration adding ``target_value`` to the UNIQUE constraint.

    The original constraint — ``(source_connector, target_connector,
    source_field, target_field, source_value)`` — omitted ``target_value``,
    so a genuinely different target proposed for the same source value was
    treated as a duplicate of whichever target got there first: ``propose()``
    silently returned the FIRST target's row, and approving it approved the
    wrong pairing. This never self-heals via ``CREATE TABLE IF NOT EXISTS``,
    so an existing table must be rebuilt on the current DDL, exactly like
    :func:`_migrate_value_pair_library` above.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'value_pair_library'"
    ).fetchone()
    if row is None:
        return  # table doesn't exist yet — created fresh on the current DDL
    existing_sql = row[0] or ""
    if "target_value" in existing_sql.split("UNIQUE", 1)[-1]:
        return  # already on the current constraint

    cols = {r[1] for r in conn.execute("PRAGMA table_info(value_pair_library)")}
    if "ops_json" not in cols:
        return  # unrecognized shape — handled by the ops_json migration first

    conn.execute("ALTER TABLE value_pair_library RENAME TO value_pair_library_old2")
    conn.executescript(_MAIN_SCHEMA)  # recreates value_pair_library on the current DDL

    rows = conn.execute("SELECT * FROM value_pair_library_old2").fetchall()
    for r in rows:
        conn.execute(
            """INSERT INTO value_pair_library
               (id, source_connector, target_connector, source_field, target_field,
                source_value, target_value, ops_json, evidence_json,
                added_by, added_on, version)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                r["id"], r["source_connector"], r["target_connector"],
                r["source_field"], r["target_field"], r["source_value"],
                r["target_value"], r["ops_json"], r["evidence_json"],
                r["added_by"], r["added_on"], r["version"],
            ),
        )
    conn.execute("DROP TABLE value_pair_library_old2")
    logger.info(
        "Migrated value_pair_library: %d row(s) moved to the (…, source_value, "
        "target_value) UNIQUE constraint.",
        len(rows),
    )


def _migrate_value_pair_library_drop_approval_columns(conn: sqlite3.Connection) -> None:
    """One-time migration removing the retired manual-approval columns.

    ``status``/``reviewed_by``/``reviewed_on`` supported a human approve/
    reject workflow that has been removed — every stored pair is now
    immediately reusable. ``CREATE TABLE IF NOT EXISTS`` never alters an
    existing table, so a store created before this change keeps the old
    columns; rebuilt on the current DDL exactly like the migrations above.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(value_pair_library)")}
    if not cols or "status" not in cols:
        return  # table doesn't exist yet, or already on the current schema

    conn.execute("ALTER TABLE value_pair_library RENAME TO value_pair_library_old3")
    conn.executescript(_MAIN_SCHEMA)  # recreates value_pair_library on the current DDL

    rows = conn.execute("SELECT * FROM value_pair_library_old3").fetchall()
    for r in rows:
        conn.execute(
            """INSERT INTO value_pair_library
               (id, source_connector, target_connector, source_field, target_field,
                source_value, target_value, ops_json, evidence_json,
                added_by, added_on, version)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                r["id"], r["source_connector"], r["target_connector"],
                r["source_field"], r["target_field"], r["source_value"],
                r["target_value"], r["ops_json"], r["evidence_json"],
                r["added_by"], r["added_on"], r["version"],
            ),
        )
    conn.execute("DROP TABLE value_pair_library_old3")
    logger.info(
        "Migrated value_pair_library: %d row(s) moved off the retired "
        "status/reviewed_by/reviewed_on approval columns.",
        len(rows),
    )


def _migrate_pipeline_runs_add_batch_progress(conn: sqlite3.Connection) -> None:
    """One-time migration adding ``batch_progress_json`` to ``pipeline_runs``.

    Nullable column with no existing data to backfill, so a plain
    ``ALTER TABLE ... ADD COLUMN`` is safe here (unlike the value_pair_library
    migrations above, which touch a UNIQUE constraint and need a full rebuild).
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(pipeline_runs)")}
    if not cols or "batch_progress_json" in cols:
        return  # table doesn't exist yet, or already on the current schema
    conn.execute("ALTER TABLE pipeline_runs ADD COLUMN batch_progress_json TEXT")


def _migrate_pipeline_runs_add_interrupt(conn: sqlite3.Connection) -> None:
    """One-time migration adding ``interrupt_json`` to ``pipeline_runs``.

    Carries the pending resolver-bot question (see ``auto_pipeline/graph.py``'s
    ``get_pending_interrupt``) while a run sits in the ``waiting_for_input``
    status. Nullable, no backfill needed — same safe ``ADD COLUMN`` as
    ``batch_progress_json`` above.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(pipeline_runs)")}
    if not cols or "interrupt_json" in cols:
        return  # table doesn't exist yet, or already on the current schema
    conn.execute("ALTER TABLE pipeline_runs ADD COLUMN interrupt_json TEXT")


def init_storage() -> None:
    """Create store directories and both databases with their schemas.

    Idempotent — safe to call on every startup.
    """
    settings = get_settings()
    settings.ensure_dirs()

    with _connect(settings.main_db_path) as conn:
        conn.executescript(_MAIN_SCHEMA)
        _migrate_value_pair_library(conn)
        _migrate_value_pair_library_target_value(conn)
        _migrate_value_pair_library_drop_approval_columns(conn)
        _migrate_pipeline_runs_add_batch_progress(conn)
        _migrate_pipeline_runs_add_interrupt(conn)
        conn.commit()

    with _connect(settings.shadow_db_path) as conn:
        conn.executescript(_SHADOW_SCHEMA)
        conn.commit()


@contextmanager
def main_db() -> Iterator[sqlite3.Connection]:
    """Connection to the authoritative metadata store (auto commit/rollback)."""
    conn = _connect(get_settings().main_db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def shadow_db() -> Iterator[sqlite3.Connection]:
    """Connection to the ``recon_shadow`` schema (auto commit/rollback)."""
    conn = _connect(get_settings().shadow_db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
