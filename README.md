# Data Reconciliation — Stage 1

Reconciles two tabular extracts (a **source** and a **target**) against the
**mapping sheet** that describes how their fields correspond, and reports where
they match, where quantities break, and where rows are missing on either side.

A mapping sheet is read by an LLM; the reconciliation itself is not. The model
only ever sees mapping-sheet text and column headers, and emits a JSON
transformation contract. A deterministic engine with an allow-listed operation
set executes that contract. **No row of source or target data is sent to a
model.**

## Scope

Stage 1 is **stateless**. There is no database, no login, and no live
SAP/IBP connector — uploads are the only input. Uploaded files, parsed mapping
sheets, compiled chains, bindings and run results live in the API process's
memory for as long as that process runs. Refreshing the browser or restarting
the backend clears everything, which is the intended behaviour at this stage.

The UI has exactly two tabs:

| Tab | What it does |
|---|---|
| **Home** | Explains the flow and what the model does and does not see. |
| **Reconciliation Engine** | The wizard: comparison type → uploads → transformation spec → results. |

## The auto-reconcile flow

The wizard arms itself as soon as all three inputs — mapping sheet, source,
target — are present, from whichever step the third one lands on. It then walks
the same seven stages the manual path walks, in the same order:

```
mapping → resolve → snapshots → validate → gate → approve → run
```

Auto mode skips the *click*, never a *check*. It calls the same endpoints as
the human-driven path and refuses to approve a compiled chain it cannot fully
account for — a refusal names the specific gate that failed (field binding,
header binding, unsupported primitive, key/compare provenance, static
validation, …) rather than reporting a generic failure.

When a gate refuses, the compiled work is kept as a **working draft** and you
finish it by hand on the Mapping step. That is the designed fallback, not an
error. Replacing any of the three inputs re-arms the pipeline against the new
input signature.

## Running it locally

```bash
python -m pip install -r requirements.txt
cd frontend && npm install
```

The backend needs an Azure AI Foundry deployment. Set `AZURE_FOUNDRY_MODEL` and
`AZURE_FOUNDRY_BASE_URL`; neither has a fallback, so the LLM path fails loudly
instead of guessing an endpoint. Authentication is Azure AD via
`DefaultAzureCredential` — locally that means `az login`; there is no API key.
For local dev these two lines can go in `backend/recon_engine/.env`, which is
gitignored. Never commit real values.

```bash
# terminal 1
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

# terminal 2
cd frontend && npm run dev
```

You land on **Home** — there is no login screen.

## Deploying to Render

`render.yaml` defines two services: a Python web service running the FastAPI
app (health check at `/health`) and a static site serving the built Vite
bundle, with a SPA rewrite so deep links resolve.

Every value is supplied through the Render dashboard as `sync: false`; no
secret is committed. After the first deploy, set the two URLs that can only be
known once both services exist:

- `CORS_ALLOW_ORIGINS` on the API → the static site's full URL
- `VITE_API_BASE_URL` on the static site → the API's full URL

Because there is no `az login` on Render, `DefaultAzureCredential` resolves
through its environment stage instead: set `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`
and `AZURE_CLIENT_SECRET` for a service principal with access to the Foundry
deployment. `render.yaml` documents the optional tuning variables alongside
these.
