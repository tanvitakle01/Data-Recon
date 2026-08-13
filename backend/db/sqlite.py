"""Local-dev replacement for :mod:`backend.db.postgres`.

Temporary swap while local dev sits behind a TLS-inspecting corporate proxy
that breaks outbound calls to ``*.supabase.co`` — see
``backend/auth/local_client.py`` and ``backend/db/local_kek.py`` for the rest
of the swap. Nothing here is deleted from the Postgres/Supabase path; this is
a parallel local backend, not a rewrite of it.

SQLite has no Row Level Security, so org/user isolation relies entirely on
the explicit ``WHERE org_id = ?`` / ``WHERE user_id = ?`` clauses already
present at every call site — RLS was documented in the Postgres migration as
a *second*, independently-enforced layer on top of those, so dropping it
here doesn't remove any isolation the call sites weren't already doing
themselves.

No connection pooling: a fresh ``sqlite3.connect`` per call, mirroring
``backend/recon_engine/storage/db.py``'s ``_connect(path)`` convention — this
is single-process local dev, not a production deployment target.
"""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Iterator

from backend.settings import get_app_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name     TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS organizations (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS org_members (
    org_id     TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role       TEXT NOT NULL DEFAULT 'owner',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (org_id, user_id)
);

CREATE TABLE IF NOT EXISTS connections (
    id                 TEXT PRIMARY KEY,
    org_id             TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name               TEXT NOT NULL,
    kind               TEXT NOT NULL CHECK (kind IN ('s4', 'ibp')),
    base_url           TEXT NOT NULL,
    service            TEXT NOT NULL,
    sap_client         TEXT,
    auth_type          TEXT NOT NULL DEFAULT 'basic'
                       CHECK (auth_type IN ('basic', 'oauth2_client_credentials', 'x509')),
    environment        TEXT NOT NULL DEFAULT 'dev' CHECK (environment IN ('dev', 'qa', 'prod')),
    enabled            INTEGER NOT NULL DEFAULT 1,

    -- CA bundle is not a secret (a public cert), stored in plaintext scoped
    -- to the connection's org. skip_tls_verify is the explicit, non-default
    -- escape hatch — surfaced in the connections list as an "insecure" badge
    -- so it can't silently persist unnoticed.
    ca_bundle_pem      TEXT,
    skip_tls_verify    INTEGER NOT NULL DEFAULT 0,

    secret_ciphertext  BLOB NOT NULL,
    secret_nonce       BLOB NOT NULL,
    wrapped_dek        BLOB NOT NULL,
    dek_nonce          BLOB NOT NULL,
    kek_key_id         TEXT NOT NULL,
    encryption_version INTEGER NOT NULL DEFAULT 1,

    last_tested_at     TEXT,
    last_test_status   TEXT CHECK (last_test_status IN ('success', 'failure')),
    last_test_message  TEXT,
    last_used_at       TEXT,

    created_by         TEXT NOT NULL REFERENCES users(id),
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    updated_by         TEXT REFERENCES users(id),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE (org_id, name)
);

CREATE TABLE IF NOT EXISTS sessions (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(id),
    org_id       TEXT NOT NULL REFERENCES organizations(id),
    token_hash   TEXT NOT NULL UNIQUE,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    user_agent   TEXT,
    ip           TEXT,
    revoked_at   TEXT
);

CREATE TABLE IF NOT EXISTS auth_audit_log (
    id            TEXT PRIMARY KEY,
    org_id        TEXT REFERENCES organizations(id),
    actor_user_id TEXT REFERENCES users(id),
    action        TEXT NOT NULL,
    entity_type   TEXT,
    entity_id     TEXT,
    metadata      TEXT NOT NULL DEFAULT '{}',
    ip            TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id),
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    used_at    TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_connections_org ON connections(org_id);
CREATE INDEX IF NOT EXISTS idx_org_members_user ON org_members(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_auth_audit_org ON auth_audit_log(org_id);
CREATE INDEX IF NOT EXISTS idx_password_reset_token_hash ON password_reset_tokens(token_hash);
"""


def _connect() -> sqlite3.Connection:
    settings = get_app_settings()
    conn = sqlite3.connect(settings.sqlite_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate_connections_columns(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a local.db may already exist.
    ``CREATE TABLE IF NOT EXISTS`` above only applies to a fresh file."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(connections)")}
    if "ca_bundle_pem" not in existing:
        conn.execute("ALTER TABLE connections ADD COLUMN ca_bundle_pem TEXT")
    if "skip_tls_verify" not in existing:
        conn.execute("ALTER TABLE connections ADD COLUMN skip_tls_verify INTEGER NOT NULL DEFAULT 0")


def init_schema() -> None:
    """Create the local SQLite file and its tables if they don't exist yet."""
    settings = get_app_settings()
    Path(settings.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(_connect()) as conn:
        conn.executescript(_SCHEMA)
        _migrate_connections_columns(conn)
        conn.commit()


@contextlib.contextmanager
def app_scoped_connection(org_id: str) -> Iterator[sqlite3.Connection]:
    """Signature-compatible with the Postgres version. ``org_id`` isn't used
    to set any session variable (no RLS in SQLite) — it exists so call sites
    don't need to change; isolation comes from each query's own ``WHERE
    org_id = ?``.
    """
    with contextlib.closing(_connect()) as conn:
        yield conn


@contextlib.contextmanager
def user_scoped_connection(user_id: str) -> Iterator[sqlite3.Connection]:
    with contextlib.closing(_connect()) as conn:
        yield conn


@contextlib.contextmanager
def app_connection() -> Iterator[sqlite3.Connection]:
    with contextlib.closing(_connect()) as conn:
        yield conn


@contextlib.contextmanager
def admin_connection() -> Iterator[sqlite3.Connection]:
    with contextlib.closing(_connect()) as conn:
        yield conn
