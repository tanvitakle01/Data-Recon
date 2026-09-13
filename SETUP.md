
# Setup

Stage-1 is a stateless, file-upload-only build: no login, no database, no
live SAP/IBP connectors. The only external call the backend makes is to an
LLM endpoint (mapping-sheet classification, header binding, and value-pairing
when the "Use data" checkbox is checked). Everything else — uploaded files,
parsed mapping sheets, compiled chains, bindings, run results — lives in
process memory for as long as the backend keeps running; closing the browser
tab or restarting the backend loses it, which is correct behavior at this
stage.

## 1. Install dependencies

```
python -m pip install -r requirements.txt
cd frontend && npm install
```

## 2. Configure the LLM endpoint

Set these two environment variables before starting the backend — there is
no hardcoded fallback for either, so the LLM call path fails loudly (never
silently, never against the wrong endpoint) if either is missing:

```
AZURE_FOUNDRY_MODEL=<your deployment/model id>
AZURE_FOUNDRY_BASE_URL=<your Azure AI Foundry OpenAI-compatible base URL>
```

Authentication to Azure AI Foundry is via Azure AD (`DefaultAzureCredential`)
— sign in once with `az login` (or run somewhere with a managed identity /
service principal already available); there is no API key to configure.

For local development, you can instead drop these two lines into
`backend/recon_engine/.env` (already gitignored — never commit real values
there or anywhere else in the repo).

## 3. Run the app

```
# terminal 1
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

# terminal 2
cd frontend && npm run dev
```

Open the frontend dev server URL. You should land straight on **Home** — no
login screen. The sidebar has exactly two entries: **Home** and
**Reconciliation Engine**.

## 4. Verify the mapping-sheet-only flow

1. Go to **Reconciliation Engine**, pick a dataset type.
2. Upload a source file and a target file (file upload is the only option —
   there's no live-connector chooser).
3. Leave the **Use data** checkbox unchecked, and go through Mapping.
4. Confirm Results renders end to end.
5. Refresh the page — confirm everything above is gone (no pre-filled data,
   no stored run). That's expected: Stage-1 keeps no state across a fresh
   page load.
