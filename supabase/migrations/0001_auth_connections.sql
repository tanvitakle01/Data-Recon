  -- Auth portal + encrypted Connections schema.
--
-- Run this once against a Supabase Postgres project (SQL editor, or
-- `supabase db push`). Requires the Vault extension, which is enabled by
-- default on Supabase-hosted projects.
--
-- This file contains NO secrets and is safe to commit as-is. It creates the
-- `app_backend` role's identity, grants, and RLS-relevant flags, but
-- deliberately does NOT set its password — a role with no password set
-- simply cannot authenticate until one is configured. The password (and the
-- Vault KEK) are provisioned separately, after this migration runs, by
-- `scripts/provision_supabase_secrets.py` — see SETUP.md. That split keeps
-- every reviewable, non-secret piece of this schema in version control
-- while nothing secret ever touches a committed file.

create extension if not exists pgcrypto;

-- === Organizations & membership ==============================================
-- One org per signup today; org_members carries a role column from day one so
-- invites/multiple members can be added later without a schema rewrite.

create table if not exists organizations (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  created_by  uuid not null references auth.users(id),
  created_at  timestamptz not null default now()
);

create table if not exists org_members (
  org_id      uuid not null references organizations(id) on delete cascade,
  user_id     uuid not null references auth.users(id) on delete cascade,
  role        text not null default 'owner',
  created_at  timestamptz not null default now(),
  primary key (org_id, user_id)
);

-- === Connections (envelope-encrypted secrets) ================================
-- Secret material is never stored in plaintext: secret_ciphertext is the
-- payload encrypted under a per-row DEK, wrapped_dek is that DEK encrypted
-- under the KEK named by kek_key_id (held in Vault, fetched by the backend
-- only). No column here can ever satisfy "return the secret to the client".

create table if not exists connections (
  id                  uuid primary key default gen_random_uuid(),
  org_id              uuid not null references organizations(id) on delete cascade,
  name                text not null,
  kind                text not null check (kind in ('s4', 'ibp')),
  base_url            text not null,
  service             text not null,
  sap_client          text,
  auth_type           text not null default 'basic'
                      check (auth_type in ('basic', 'oauth2_client_credentials', 'x509')),
  environment         text not null default 'dev' check (environment in ('dev', 'qa', 'prod')),
  enabled             boolean not null default true,

  secret_ciphertext   bytea not null,
  secret_nonce        bytea not null,
  wrapped_dek         bytea not null,
  dek_nonce           bytea not null,
  kek_key_id          text not null,
  encryption_version  int not null default 1,

  last_tested_at      timestamptz,
  last_test_status    text check (last_test_status in ('success', 'failure')),
  last_test_message   text,
  last_used_at         timestamptz,

  created_by          uuid not null references auth.users(id),
  created_at          timestamptz not null default now(),
  updated_by          uuid references auth.users(id),
  updated_at          timestamptz not null default now(),

  unique (org_id, name)
);

-- === Server-owned session store (backs the opaque httpOnly cookie) ===========
-- The cookie holds a random token; only its SHA-256 hash is ever persisted,
-- so a full DB dump alone cannot be replayed as a valid session.

create table if not exists sessions (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id),
  org_id        uuid not null references organizations(id),
  token_hash    text not null unique,
  created_at    timestamptz not null default now(),
  expires_at    timestamptz not null,
  last_seen_at  timestamptz not null default now(),
  user_agent    text,
  ip            inet,
  revoked_at    timestamptz
);

-- === Auth/connections audit trail =============================================
-- Separate from the existing SQLite recon audit_log (backend/recon_engine/storage/db.py),
-- which stays untouched and keeps tracking reconciliation-run activity.

create table if not exists auth_audit_log (
  id             uuid primary key default gen_random_uuid(),
  org_id         uuid references organizations(id),
  actor_user_id  uuid references auth.users(id),
  action         text not null,
  entity_type    text,
  entity_id      text,
  metadata       jsonb not null default '{}',
  ip             inet,
  created_at     timestamptz not null default now()
);

create index if not exists idx_connections_org on connections(org_id);
create index if not exists idx_org_members_user on org_members(user_id);
create index if not exists idx_sessions_token_hash on sessions(token_hash);
create index if not exists idx_sessions_expiry on sessions(expires_at);
create index if not exists idx_auth_audit_org on auth_audit_log(org_id);

-- === Row Level Security ========================================================
-- RLS is the SECOND, independently-enforced isolation layer. The FastAPI
-- backend never uses the Supabase service_role key for normal requests (that
-- key bypasses RLS entirely, which would make RLS decorative); it connects as
-- the `app_backend` role below and runs `SET LOCAL app.current_org_id = ...`
-- (derived only from the verified session, never from client input) at the
-- start of every request transaction. Even a backend bug that forgets a
-- `WHERE org_id = ...` clause still cannot cross tenants, because the
-- database role itself is RLS-restricted.

alter table organizations enable row level security;
alter table org_members enable row level security;
alter table connections enable row level security;
alter table sessions enable row level security;
alter table auth_audit_log enable row level security;

-- === Dedicated non-bypass-RLS role for all normal request-scoped queries =====
-- Created with NO password — `login` alone permits password auth in
-- principle, but with no password set (`rolpassword` is null), every
-- authentication attempt is simply rejected. The role is unusable until
-- scripts/provision_supabase_secrets.py sets a real, generated password
-- out-of-band. Safe to commit; safe to re-run (guarded by the existence
-- check, and re-running never touches an already-set password).
--
-- Deliberately created here, BEFORE any policy below — several policies
-- reference `to app_backend` by name, which fails with "role does not
-- exist" if the role isn't created first.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'app_backend') then
    create role app_backend login;
  end if;
end
$$;

alter role app_backend nosuperuser nocreatedb nocreaterole nobypassrls;

grant usage on schema public to app_backend;
grant select, insert, update, delete on organizations, org_members, connections to app_backend;
grant select, insert, update, delete on sessions, auth_audit_log to app_backend;

create policy organizations_isolation on organizations
  using (id = current_setting('app.current_org_id', true)::uuid)
  with check (id = current_setting('app.current_org_id', true)::uuid);

create policy org_members_isolation on org_members
  using (org_id = current_setting('app.current_org_id', true)::uuid)
  with check (org_id = current_setting('app.current_org_id', true)::uuid);

-- Sign-in needs "which org does this just-authenticated user belong to?"
-- BEFORE org_id is known — the chicken-and-egg case org_members_isolation
-- above can't cover. Scoped narrowly by user_id (set only after Supabase
-- Auth has already verified the password), not a blanket bypass.
create policy org_members_self_lookup on org_members
  for select
  to app_backend
  using (user_id = current_setting('app.current_user_id', true)::uuid);

create policy connections_org_isolation on connections
  using (org_id = current_setting('app.current_org_id', true)::uuid)
  with check (org_id = current_setting('app.current_org_id', true)::uuid);

-- sessions / auth_audit_log: session lookup happens BEFORE org_id is known
-- (cookie -> user_id -> org_id), so these two tables are scoped by explicit
-- app_backend-only policies below rather than the org_id session variable.
-- No policy exists for any other role on these two tables, so they remain
-- deny-all to everyone except app_backend and service_role.

create policy sessions_backend_access on sessions
  for all
  to app_backend
  using (true)
  with check (true);

create policy auth_audit_log_backend_access on auth_audit_log
  for all
  to app_backend
  using (true)
  with check (true);

-- === Vault: the KEK ============================================================
-- Deliberately NOT done here. A real KEK value has no business ever existing
-- in a SQL file, migration or otherwise — this schema only needs the Vault
-- extension to be present (checked below); the secret itself is created by
-- scripts/provision_supabase_secrets.py, which generates it in memory and
-- inserts it directly via `vault.create_secret(...)`, never writing it to
-- disk. See SETUP.md for the full sequence.

do $$
begin
  if not exists (select 1 from pg_extension where extname = 'supabase_vault') then
    raise exception 'Supabase Vault extension not found — enable it in Database > Extensions before continuing.';
  end if;
end
$$;
