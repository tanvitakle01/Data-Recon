
# Supabase setup — auth portal + encrypted connections

This is the full sequence to stand up the Supabase-backed auth and
Connections feature from a fresh clone. Written for someone who has never
used Supabase before. No step here writes a real secret into a committed
file — every place a secret is needed, this guide either generates it for
you into `backend/.env` (gitignored) or has you paste it there yourself.

## 0. Before you start — the security invariant this guide preserves

Three different secrets are involved, and they are deliberately handled
three different ways:

| Secret | Lives in | Who ever sees it |
|---|---|---|
| `app_backend` Postgres password | `backend/.env` only, inside `DATABASE_URL_APP` | You, once, when the provisioning script prints/writes it |
| Connections KEK | Supabase Vault only | Nobody — not you, not this repo, only the running backend at request time |
| SAP/IBP connection secrets (usernames, passwords) | Encrypted in the `connections` table | Nobody after save — see the Connections page's write-only design |

Nothing in `supabase/migrations/*.sql` contains a real secret. If you ever
see a real password, key, or KEK value in a file under version control,
stop and treat it as already-compromised — see "If a secret leaks" at the
bottom.

## 1. Create the Supabase project

1. Go to [supabase.com](https://supabase.com), create an account/org if you
   don't have one, and create a new project.
2. Wait for provisioning to finish, then open **Project Settings → API**.
   Copy from this exact page (not from memory, not from an old tab):
   - **Project URL** → this is `SUPABASE_URL`.
   - **anon / public key** → this is `SUPABASE_ANON_KEY`.
   - **service_role key** → this is `SUPABASE_SERVICE_ROLE_KEY`.
3. Open **Project Settings → Database** and copy the **connection string**
   (URI format, "Session" or "Transaction" pooler — either works for this
   app). This is `DATABASE_URL_ADMIN`, with `postgres` as the username and
   your database password (set when the project was created, or resettable
   from this same page) filled in.

**Verify these came from the same project before moving on**: the
hostname in your connection string (`db.<project-ref>.supabase.co`) and the
`<project-ref>` in your Project URL (`https://<project-ref>.supabase.co`)
must be the *same* `<project-ref>`. It's easy to have two browser tabs open
on two different projects and mix them up — if these two refs don't match,
Auth calls and database calls will silently hit two different projects.
Re-copy both from the same **Project Settings** page if you're ever unsure.

4. Open **Database → Extensions** and confirm **Vault** (`supabase_vault`)
   is enabled. It's on by default for new projects; if it's missing here,
   enable it now — the migration in step 3 below checks for it and will
   fail loudly with a clear error if it's still missing.

## 2. Fill in `backend/.env`

Copy the template and fill in what you have so far:

```
cp backend/.env.example backend/.env
```

Fill in `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`,
`DATABASE_URL_ADMIN`, and `FRONTEND_URL` (leave the default unless your
frontend runs somewhere other than `http://localhost:5173`). **Leave
`DATABASE_URL_APP` blank** — there is no password to put there yet; that
comes from a script in step 4.

`backend/.env` is gitignored. Never move these values into
`backend/.env.example` — that file is a committed template and must only
ever contain placeholders.

## 3. Run the migration

Install the Supabase CLI (no separate download needed — `npx` fetches it):

```
npx supabase --version
```

Link this repo to your project (you'll be prompted to log in the first
time; it opens a browser):

```
npx supabase link --project-ref <your-project-ref>
```

`<your-project-ref>` is the same ref you verified in step 1 — the subdomain
of your Project URL.

Push the migration:

```
npx supabase db push
```

This creates `organizations`, `org_members`, `connections`, `sessions`,
`auth_audit_log`, all RLS policies, and the `app_backend` role (with **no**
password yet — see `supabase/migrations/0001_auth_connections.sql`'s header
comment for why). If this step fails with "Vault extension not found",
go back to step 1.4.

If you'd rather not link the project (e.g. CI), you can push directly:

```
npx supabase db push --db-url "$DATABASE_URL_ADMIN"
```

## 4. Provision the two secrets

This is the step that sets the `app_backend` password and creates the Vault
KEK — the two things the migration deliberately left undone. Run it from
the repo root with your backend virtualenv active:

```
python scripts/provision_supabase_secrets.py
```

What it does, and why it's safe to commit the *script* but never its
*output*:
- Generates a random 64-character hex password with `secrets.token_hex(32)`
  and runs `ALTER ROLE app_backend PASSWORD ...` directly against
  `DATABASE_URL_ADMIN`. The password only ever exists in this process's
  memory and in the `DATABASE_URL_APP` line it writes to `backend/.env`.
- Generates 32 random bytes with `secrets.token_bytes(32)` and inserts them
  into Supabase Vault via `vault.create_secret(...)` under the name in
  `KEK_VAULT_SECRET_NAME` (default `connections_kek_v1`). **This value is
  never printed, logged, or written anywhere** — the backend fetches it from
  Vault at request time via the service_role connection
  (`backend/db/vault.py`); no human needs to see it, ever.
- Writes the resulting `DATABASE_URL_APP=postgresql://app_backend:<password>@<same host as DATABASE_URL_ADMIN>` line into `backend/.env` for you.

Expected output looks like:
```
app_backend password rotated.
Vault secret 'connections_kek_v1': created.

DATABASE_URL_APP written to .../backend/.env.
```

Safe to re-run later (e.g. to rotate the `app_backend` password): it always
rotates the password and rewrites `DATABASE_URL_APP`, but leaves an
already-existing Vault secret alone (reports `already exists` instead of
creating a duplicate).

If you'd rather see the value than have it written automatically, pass
`--no-write-env` and paste it into `backend/.env` yourself.

## 5. Install Python/Node dependencies

```
python -m pip install -r requirements.txt
cd frontend && npm install
```

## 6. Run the app

```
# terminal 1
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

# terminal 2
cd frontend && npm run dev
```

## 7. Verify authentication

1. Open `http://localhost:5173` — you should land on `/login` (no session
   yet).
2. Click **Create an account**, fill in the form (this creates a brand-new
   organization owned by you — see the signup flow's design), submit.
3. You should land on `/home`, authenticated.
4. Open your browser's dev tools → Application/Storage → Cookies. Confirm
   there's a `dr_session` cookie, marked **HttpOnly**, and that
   `document.cookie` in the console does **not** show it (that's httpOnly
   actually working).
5. Sign out, confirm you're bounced back to `/login` and the cookie is gone.
6. Try **Forgot password?** with a real email you control — confirm you get
   a reset email and can set a new password through the flow.

## 8. Verify encrypted connection storage

1. Sign in, go to **Settings → Connections → Add connection**.
2. Fill in a test S/4 or IBP connection (use real credentials if you have a
   sandbox system, otherwise expect **Test Connection** to fail with a
   sanitized message — that's the point of requiring it before Save).
3. Confirm **Save** is disabled until Test Connection succeeds.
4. After saving, open your browser's Network tab, reload the Connections
   list, and inspect the raw response body for `GET /api/connections` — it
   must not contain your password/secret anywhere, in any field.
5. In the Supabase dashboard's **Table Editor**, open `connections` and
   confirm `secret_ciphertext`/`wrapped_dek` are opaque binary blobs, not
   readable text.
6. (Optional, stronger check) In the SQL editor, run as the project owner:
   ```sql
   select * from connections;
   ```
   You'll see the row (service_role bypasses RLS, as designed). Then, to
   confirm RLS itself is doing something, you'd need a second Postgres
   session authenticated as `app_backend` with a *different*
   `app.current_org_id` set — see the verification section in the original
   implementation plan for the exact `SET LOCAL` steps.

## If a secret leaks

If a real password, key, or KEK value ever ends up in a committed file or
this conversation history:
- **Postgres passwords** (`app_backend`, `postgres`/service DB password):
  re-run `python scripts/provision_supabase_secrets.py` to rotate
  `app_backend` immediately; reset the `postgres` password from
  **Project Settings → Database**.
- **Supabase API keys** (`anon`, `service_role`): regenerate from
  **Project Settings → API**.
- **The KEK**: there is no rotation path implemented yet for re-encrypting
  existing `connections` rows under a new KEK — treat a leaked KEK as a
  reason to also re-save every existing connection's credentials (which
  re-encrypts them) after rotating, not just swap the Vault secret.
