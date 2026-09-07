# Architecture Report: Transformation Spec → AI Rules → Executable Transformations

> Status: analysis only — no code changed. Produced to determine how to build the
> Transformation Spec → AI Rules feature on existing infrastructure rather than a
> parallel implementation.

## Executive summary

**The infrastructure this feature needs already exists** — it is the
`backend/recon_engine/` package, which implements exactly the pattern the feature
requires: *LLM emits a JSON Transformation Contract → deterministic engine executes
it*. The core invariant (`recon_engine/__init__.py`) is **"LLM output = Data, Engine
output = Execution"** — the Groq LLM may only emit a validated JSON contract; it
never generates or runs code.

The gap is **not** a missing engine. The gap is that the **frontend wizard and the
primary `/reconcile` endpoint are wired to the legacy v1 Excel-comparator path**,
which ignores the `rulesText` and `mappingSheet` the Transformation Spec step
already collects. There are effectively **two parallel backends** today, and the
AI-rules feature means bridging the wizard to the already-built v2 contract
lifecycle rather than writing anything new.

> ⚠️ **Security finding (flag immediately):** a **live Groq API key is committed in
> `backend/.env`** (`GROQ_API_KEY=gsk_...`). Rotate it and remove it from version
> control regardless of this feature.


## The two coexisting backends

| | **v1 — legacy (LIVE, wired to wizard)** | **v2 — recon_engine (BUILT, not wired to wizard)** |
|---|---|---|
| Entry routes | `/reconcile`, `/automap`, `/preview`, `/insights` | `/api/recon/*` (`contracts.py`, `recon_v2.py`) |
| Engine | `excel_comparator/core/comparator.py` | `recon_engine/engine/{executor,reconciler}.py` |
| Transformations | Implicit only (trim, lowercase, numeric coerce) | **Explicit, allow-listed operations from a contract** |
| Rules/AI | **None** — `rulesText` is collected but ignored | **Groq compiles rules → JSON contract** |
| State | Stateless, in-memory `_FILE_STORE` dict (lost on restart) | Persisted: SQLite + JSON frames + audit log |
| Matching | Target-anchored composite key, `Remarks` column | Full-outer-join, 5-way classification, lineage |

---

## 1. Folder structure relevant to transformations

```text
backend/
├── recon_engine/                    ★ THE TARGET SUBSYSTEM (LLM→contract→execute)
│   ├── __init__.py                  invariant: "LLM output = Data"
│   ├── service.py                   orchestration: compile→validate→approve→run
│   ├── config.py                    GroqSettings (GROQ_API_KEY / GROQ_MODEL / GROQ_BASE_URL)
│   ├── compiler/
│   │   ├── base.py                  ContractCompiler ABC + ContractCompilerError
│   │   ├── groq_compiler.py         ★ Groq LLM integration (only real LLM in backend)
│   │   └── stub_compiler.py         deterministic fallback when no API key
│   ├── models/
│   │   ├── contract.py              ★ DraftContract / TransformationContract (the "rules" schema)
│   │   ├── results.py, run.py, snapshot.py, audit.py
│   ├── operations/
│   │   ├── ops.py                   pandas implementations of each operation
│   │   └── registry.py              ★ fixed allow-list of 11 operations
│   ├── engine/
│   │   ├── executor.py              build_shadow_source (applies contract ops in order)
│   │   └── reconciler.py            full-outer-join + classification
│   ├── validation/
│   │   ├── gate1_structural.py      schema/field/op validation
│   │   └── gate2_replay.py          sample-replay sanity checks
│   └── storage/                     SQLite + JSON frame persistence + audit
│
├── excel_comparator/core/           v1 engine (LIVE path today)
│   ├── auto_mapper.py               heuristic column mapping (difflib, no AI)
│   ├── mapper.py                    ColumnMapper (key_fields/compare_fields)
│   ├── comparator.py                4-scenario Remarks-based compare
│   ├── date_alignment.py, loader.py, writer.py
│   └── utils/helpers.py             normalise_value, build_composite_key
│
├── ai/                              ⚠️ NAME IS MISLEADING — no LLM here
│   ├── insight_engine.py            deterministic rule-based analytics
│   └── insight_adapter.py           cockpit payload reshaping (no LLM)
│
├── services/                        excel_service, mapping_service, reconciliation_service
├── routes/                          HTTP layer (see §2)
└── models/schemas.py                pydantic (mostly unused by live routes)

frontend/src/reconciliation/
├── steps/TransformationSpecStep.jsx ★ where rules/mapping sheet are collected
├── steps/ReconciliationRunStep.jsx  calls /reconcile
├── components/MappingEditor.jsx      key/compare field editor
├── context/wizardReducer.js          ★ transformationSpec state
├── lib/payload.js                    FormData builder for /automap & /reconcile
└── services/api.js                   axios (baseURL http://localhost:8000)
```

---

## 2. Existing API endpoints

**v1 (wired to wizard today):**

- `POST /automap` — multipart source/target → heuristic mapping `{display, mapping, date_alignment}`
- `POST /reconcile` — multipart; accepts `mapping_json`, and **already receives
  `rules_text`, `comparison_type`, `mapping_sheet_name` but ignores them**
  (`reconcile.py` only reads `mapping_json`, `scenarios`, `date_scope`)
- `POST /preview`, `GET /api/files/download/{file_id}`, `POST /insights*`
- SAP connectors: `/api/connectors/{ibp,s4}/*`

**v2 contract lifecycle (`/api/recon`, BUILT, not called by wizard):**

- `GET /api/recon/operations` — discovery of the allow-listed operations (feeds a UI)
- `POST /api/recon/contracts/compile` — `{mapping_sheet, rules, source_schema,
  target_schema, comparison_type, source_type, target_type}` → `DraftContract`
  (**this is the AI-rules endpoint**)
- `POST /api/recon/contracts/validate` — Gate 1 + Gate 2 → report
- `POST /api/recon/contracts/approve` → versioned `TransformationContract`
- `GET /api/recon/contracts/{id}` and `/{id}/approved`
- `POST /api/recon/snapshots` — ingest immutable Raw_Source/Raw_Target
- `POST /api/recon/runs` — deterministic execution → results
- `GET /api/recon/runs/{id}`, `/results/{id}`, `/audit`

**Dead code (never registered in `main.py`):** `routes/upload.py`, `routes/mapping.py`,
`routes/sap_preview.py`, `routes/auto_map_preview.py`. Do not build on these.

---

## 3. Existing state objects / interfaces

**Frontend wizard state** (`wizardReducer.js` → `createInitialWizardState`):

```js
{
  step, stepStatus,
  source: { connectorId, kind, dataset, status, error },
  target: { /* same */ },
  comparisonType: { id, label } | null,
  transformationSpec: {
    mappingSheet: { name, size, file } | null,   // ← uploaded, not parsed yet
    rulesText: "",                                // ← free text, IGNORED downstream today
    mapping: { display:[...], mapping:{key_fields,compare_fields,options} } | null,
  },
  reconciliation: <'/reconcile' response> | null,
}
dataset = { datasetId, filename, columns, preview, rowCount, colCount, rows|null, file|null, sheet, sheets, fetchedAt }
```

**Backend v1 mapping object** (produced by `auto_mapper`, consumed by `ColumnMapper`):

```json
{ "key_fields":[{"source_col","target_col"}],
  "compare_fields":[{"source_col","target_col"}],
  "options":{"case_insensitive":true,"trim_whitespace":true} }
```

**Backend v2 contract** (`recon_engine/models/contract.py` — the real "rules" model):

```python
ContractOperation { op: str, field: str|None, params: dict }   # extra="forbid", NO code field
BusinessKeyField  { source_field, target_field }
CompareField      { source_field, target_field, match_type: EXACT|TOLERANCE, tolerance: float|None }
DraftContract / TransformationContract {
  comparison_type, source_type, target_type,
  operations: [ContractOperation],       # applied IN ORDER: Raw_Source → Shadow_Source
  business_key: [BusinessKeyField],
  compare_fields: [CompareField],
  source_schema: [str], target_schema: [str],
  options: {case_insensitive, trim_whitespace}, notes,
  # + approval_status, contract_id, contract_version(≥1), approved_by, compiler
}
```

---

## 4. Existing AI integration points

- **Only Groq, only one place:** `recon_engine/compiler/groq_compiler.py`.
  - SDK: official `groq` package (`from groq import Groq`), lazy-imported (optional
    dep — **not in `requirements.txt`; needs `pip install groq`**).
  - Model: `GROQ_MODEL` env, default `llama-3.3-70b-versatile`.
  - Call: `chat.completions.create(temperature=0, response_format={"type":"json_object"})`.
  - Prompt: system preamble enforces "JSON only, ops must come from
    `allowed_operations`, reference only given schema columns, never emit
    SQL/Python/pandas"; user message includes `mapping_sheet`, `rules`, schemas,
    `allowed_operations`, and `DraftContract.model_json_schema()` as
    `required_output_schema`.
  - Selection: Groq used only when `GROQ_API_KEY` set (`service._default_compiler`),
    else `StubContractCompiler` (deterministic, keeps everything runnable offline).
- **`backend/ai/` is NOT AI** — despite the name, `insight_engine.py` /
  `insight_adapter.py` are 100% deterministic Python analytics over the
  reconciliation `Remarks` column. No LLM. Do not confuse this with the feature.

---

## 5. Existing transformation / mapping models

- **Implicit transformations in the v1 compare path** (`excel_comparator`): header
  trim, `normalise_value` (NaN→"", trim, lowercase), pipe-joined composite key,
  numeric coercion with **exact** equality (no tolerance/rounding). Date alignment
  exists but is **not** applied inside `comparator.run` — it's a separate preview path.
- **Explicit transformation model = the contract operations registry**
  (`recon_engine/operations/registry.py`), a fixed allow-list of 11 ops with per-op
  param validation:
  - Transforms: `identity_cast_string`, `trim_string`, `numeric_cast`, `date_parse`
    (req `source_format`), `rename_field` (req `to`)
  - Filters: `reject_null`, `exclude_value` (req `values`)
  - Aggregates: `group_by` (req `by`), `sum_aggregate` (req `by`)
  - Compares: `exact_match`, `tolerance_match` (req `tolerance`)
- **Mapping models:** v1 `ColumnMapper` (`key_fields`/`compare_fields`) ↔ v2
  `business_key`/`compare_fields`. Structurally close but not identical (`source_col`
  vs `source_field`, plus v2 adds `match_type`/`tolerance` and ordered `operations`).

---

## 6. Data flow trace + where rules should be injected

**Current live flow (v1):**

```text
Source Dataset ─┐
                ├─ appendDatasetSide() → FormData (files or *_rows JSON)
Target Dataset ─┘
        │
        ▼  TransformationSpecStep
   POST /automap ──► auto_map_columns() [heuristic] ──► mapping {key_fields,compare_fields}
        │            rulesText + mappingSheet collected into wizard state …but go nowhere
        ▼  ReconciliationRunStep
   POST /reconcile (mapping_json, rules_text*, comparison_type*, mapping_sheet_name*)
        │            (* accepted by the form but NEVER read by reconcile.py)
        ▼
   build_alignment → filter overlap → ColumnMapper.validate → ExcelComparator.run([1,2,3,4])
        ▼
   Results (annotated Remarks df + summary + download_url)
```

**The injection point is between Transformation Spec and Reconciliation.** The
`rulesText` + `mappingSheet` + schemas should flow into the **existing**
`POST /api/recon/contracts/compile` → `validate` → `approve`, producing a
`TransformationContract`; then reconciliation should run through `recon_engine`
(snapshots → run) so the contract's `operations` are actually applied
(`build_shadow_source`) before comparison. Today those rules dead-end in wizard state.

**Target flow (reusing v2):**

```text
Source/Target Dataset → ingest snapshots (POST /api/recon/snapshots)
Comparison Type + mappingSheet(display) + rulesText + schemas
     → POST /api/recon/contracts/compile   [Groq → DraftContract JSON]
     → POST /api/recon/contracts/validate   [Gate 1 structural + Gate 2 replay]
     → (Transformation Preview = render DraftContract.operations as JSON) ← Section D already stubbed for this
     → POST /api/recon/contracts/approve    [versioned TransformationContract]
     → POST /api/recon/runs                 [deterministic: shadow build → full outer join → classify]
     → Results
```

Note: `TransformationSpecStep.jsx` **Section D** literally renders *"Transformation
Preview (JSON Rules) — Available after LLM integration"* — it's a pre-built
placeholder for the compiled contract JSON.

---

## 7. Components / services to REUSE

- **`recon_engine/service.py`** — the single orchestration API (`compile_draft`,
  `validate_draft`, `approve_contract`, `ingest_snapshot`, `run_reconciliation`).
  Drive everything through this.
- **`recon_engine/compiler/groq_compiler.py`** + `StubContractCompiler` — do not
  write a new LLM client; this already enforces JSON-only, schema-constrained output
  with an offline fallback.
- **`recon_engine/models/contract.py`** — adopt `DraftContract`/`TransformationContract`
  as *the* rules representation.
- **`recon_engine/operations/registry.py`** + `GET /api/recon/operations` — the
  allow-list is the contract between LLM output and executor; expose it to the UI for
  the transformation preview.
- **Validation gates** — reuse as-is; they're the safety layer that makes LLM output
  trustworthy.
- **Frontend:** `wizardReducer` `transformationSpec` state, `MappingEditor`,
  `payload.js`, `api.js`, and the existing Section D placeholder.
- **`services/excel_service.py`** (`frame_to_records` / `records_to_frame`) for
  snapshot ingestion payloads.

## 8. Components / services to NOT duplicate

- ❌ Don't build a new LLM client, prompt layer, or JSON-rules schema —
  `groq_compiler` + `contract.py` exist.
- ❌ Don't create a new operations/rule engine — `operations/registry.py` +
  `engine/executor.py` exist and are tested.
- ❌ Don't extend the v1 `/reconcile` + `ExcelComparator` to interpret `rules_text` —
  that would create a *third* parallel transformation path. Route rules through v2.
- ❌ Don't reintroduce a static dataset-type registry. Dataset types are the
  interface list read from the uploaded mapping workbook
  (`recon_engine/interface_index.py`); `comparison_type` on a contract is the
  slug of the chosen interface's name, and contracts carry the rest of that
  config.
- ❌ Don't revive the dead route files (`upload.py`, `mapping.py`,
  `auto_map_preview.py`, `sap_preview.py`, `comparison_types.py`).
- ❌ Don't touch `backend/ai/` for this — it's deterministic insight analytics, unrelated.

---

## Key decisions to resolve before implementation

1. **Bridge vs. migrate:** wire the wizard to v2 `/api/recon/*` (recommended — gets
   persistence, audit, gates, real transformations), *or* the lighter-but-inferior
   option of teaching v1 `/reconcile` to accept a compiled contract. The two engines
   classify differently (v1 4-scenario `Remarks` vs v2 5-way `RecordClass`), so
   `ReconciliationResults.jsx` may need to handle the v2 result shape.
2. **Mapping-sheet parsing:** `mappingSheet` is currently uploaded as a raw file but
   never parsed; `compile` expects `mapping_sheet: list[dict]`. Something must parse
   it (reuse `excel_service`).
3. **Snapshot ingestion for Excel uploads:** v2 works from ingested row snapshots;
   Excel-file datasets (which keep only a `file` handle + preview client-side) need
   their rows materialized to ingest.
4. **`groq` dependency** must be added to `requirements.txt`, and the committed API
   key rotated.
