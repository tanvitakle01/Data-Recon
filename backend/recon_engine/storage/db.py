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

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from backend.recon_engine.config import get_settings

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


def init_storage() -> None:
    """Create store directories and both databases with their schemas.

    Idempotent — safe to call on every startup.
    """
    settings = get_settings()
    settings.ensure_dirs()

    with _connect(settings.main_db_path) as conn:
        conn.executescript(_MAIN_SCHEMA)
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
