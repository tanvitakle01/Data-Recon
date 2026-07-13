# Reconciliation Engine (`backend/recon_engine`)

A contract-driven, deterministic reconciliation architecture.

> **Core principle**
> The LLM **never** generates executable code. It may only produce a structured
> **Transformation Contract (JSON)**. A deterministic engine executes that
> contract using a fixed, allow-listed operation registry.
>
> ```
> LLM output    = Data       (a Transformation Contract, JSON only)
> Engine output = Execution  (deterministic, allow-listed operations)
> ```
>
> No generated Python, SQL, Spark, pandas expressions, `eval`, dynamic code
> execution, or arbitrary scripts are ever permitted anywhere in this system.

---

## Lifecycle

```
                 ┌──────────────── COMPILE (LLM-assisted) ────────────────┐
Mapping Sheet ─┐ │                                                        │
   + Rules  ───┼▶│  Groq LLM ──▶ Draft Contract JSON                      │
               │ │      │            │                                    │
 (source/target│ │      │            ▼                                    │
  schemas from │ │      │      Gate 1: Structural validation              │
  connectors / │ │      │            ▼                                    │
  uploads)     │ │      │      Gate 2: Sample replay (50–100 rows)        │
               │ │      │            ▼                                    │
               │ │      │      Human Approval  ──▶ Versioned Contract     │
               │ └──────┼─────────────────────────────┬──────────────────┘
               │        │  (LLM emits JSON only —      │
               │        │   never code, never data)    ▼
               │                              ┌──── RUNTIME (no LLM) ─────┐
               │   Raw_Source (immutable) ───▶│ Deterministic Engine       │
               │                              │   apply contract ops       │
               │                              │        ▼                    │
               │                              │   Shadow_Source (derived)   │
               │   Raw_Target (immutable) ───▶│        │                    │
               │                              │  FULL OUTER JOIN on         │
               │                              │  business key + tolerances  │
               │                              │        ▼                    │
               │                              │  Classify → Results         │
               │                              └────────────────────────────┘
```

Terminal classifications: **match · mismatch · missing_in_source ·
missing_in_target · exception**.

---

## Module map

| Module | Responsibility |
|---|---|
| `config.py` | Env-driven settings (`GROQ_API_KEY`, `RECON_STORE_DIR`, `SHADOW_TTL_DAYS`, sample sizes). |
| `models/` | Pydantic models: `TransformationContract`, `RawSnapshot`, `ShadowSource`, `ReconciliationRun`, `ReconciliationResult`, `AuditEvent`. |
| `operations/` | The **allow-listed operation registry** + hand-written, tested op implementations. |
| `compiler/` | `GroqContractCompiler` (LLM scaffolding) and `StubContractCompiler` (deterministic placeholder). Both emit **contract JSON only**. |
| `validation/` | Gate 1 (structural) and Gate 2 (sample replay). |
| `engine/` | `executor` (Raw_Source → Shadow_Source) and `reconciler` (full outer join + classify). No LLM. |
| `storage/` | Durable persistence: SQLite (`recon.db`, `recon_shadow.db`) + on-disk frames. Immutable snapshots, versioned contracts, runs, results, shadow (TTL), audit log. |
| `service.py` | Orchestration wiring every step, with audit events. |

HTTP surface: `backend/routes/contracts.py` and `backend/routes/recon_v2.py`
(both under `/api/recon`).

---

## The allow-listed operation registry

A contract may reference **only** these operations (`operations/registry.py`).
Each is implemented by hand in `operations/ops.py` and unit-tested. If a
contract names anything else, **Gate 1 rejects it** — operations are never
auto-created.

| Operation | Kind | Purpose |
|---|---|---|
| `identity_cast_string` | transform | Cast a column to string (nulls preserved). |
| `trim_string` | transform | Strip whitespace. |
| `numeric_cast` | transform | Coerce to numeric (unparseable → null). |
| `date_parse` | transform | Parse from `source_format` → `canonical_format`. |
| `rename_field` | transform | Rename a column. |
| `reject_null` | filter | Drop rows where the field is null/blank. |
| `exclude_value` | filter | Drop rows whose field is in a value list. |
| `group_by` | aggregate | Collapse to one row per key combination. |
| `sum_aggregate` | aggregate | Group by keys and sum a field. |
| `exact_match` | compare | Exact (numeric or normalised string) equality. |
| `tolerance_match` | compare | Numeric equality within an absolute tolerance. |

A contract is **data**. There is deliberately no field anywhere in the schema
for code, expressions, or scripts (`ContractOperation` uses `extra="forbid"`).

---

## Immutability, shadow, lineage, TTL

* **Raw layer is immutable.** `snapshot_store` exposes *no* update/delete;
  every extract/upload is a new append-only snapshot with `snapshot_id`,
  `snapshot_hash` (SHA-256 of the canonical payload), timestamp, and lineage.
* **Shadow_Source is derived and disposable.** Raw_Source is never modified —
  the contract's operations produce a *separate* Shadow_Source. Each shadow row
  carries `__source_row_ids__` referencing the raw rows it came from.
* **Reproducibility.** A Shadow_Source is fully reproducible from
  `raw_snapshot_hash` + `contract_version`.
* **TTL.** Shadow sources live in the `recon_shadow` schema (`recon_shadow.db`)
  and expire after `SHADOW_TTL_DAYS` (default **7**). `service.cleanup_expired_shadows()`
  removes expired payloads + rows and writes an audit event.
* **Audit + persistence.** Snapshots, approved contracts, runs, results, and a
  full audit log are persisted in `recon.db`. Nothing ever persists a
  modification to a raw dataset.

---

## Groq configuration — where the API key is required

The Groq LLM is used **only** in the compile phase, and **only** inside
`compiler/groq_compiler.py::GroqContractCompiler.compile()`. Nothing else —
validation, approval, the deterministic engine, reconciliation, persistence —
needs Groq or any network access.

Environment variables:

| Variable | Required? | Default | Used by |
|---|---|---|---|
| `GROQ_API_KEY` | Only for the real Groq compile phase | *(unset)* | `GroqContractCompiler` |
| `GROQ_MODEL` | No | `llama-3.3-70b-versatile` | `GroqContractCompiler` |
| `GROQ_BASE_URL` | No | Groq default | `GroqContractCompiler` |
| `RECON_STORE_DIR` | No | `<repo>/data/recon_store` | persistence |
| `SHADOW_TTL_DAYS` | No | `7` | shadow TTL |
| `REPLAY_SAMPLE_MIN` / `REPLAY_SAMPLE_MAX` | No | `50` / `100` | Gate 2 |

### Current status of the Groq integration

**Scaffolding only.** The plumbing is in place — config, lazy SDK client
construction, prompt assembly (system preamble + the allow-listed registry +
the required JSON output schema), and the safety contract that the response is
parsed as JSON into a `DraftContract`. The actual model call and
contract-generation intelligence are **intentionally not implemented yet**;
`GroqContractCompiler.compile()` raises `ContractCompilerError` with guidance.

To make the lifecycle runnable today, use `StubContractCompiler`, a
deterministic placeholder that derives a minimal valid contract straight from
the mapping sheet. It emits the same JSON shape the LLM will eventually produce,
so nothing downstream depends on which compiler was used.

To enable the LLM later:

1. `pip install groq`
2. Set `GROQ_API_KEY` (and optionally `GROQ_MODEL` / `GROQ_BASE_URL`).
3. Implement the chat completion in `GroqContractCompiler.compile()` using the
   already-assembled prompt, parse the JSON-only response into a `DraftContract`,
   and return it. Everything after that (Gate 1, Gate 2, approval, execution)
   already works unchanged.

---

## HTTP API (`/api/recon`)

Compile / validate / approve (`routes/contracts.py`):

* `GET  /api/recon/operations` — the allow-listed registry.
* `POST /api/recon/contracts/compile` — mapping sheet + rules → draft contract.
* `POST /api/recon/contracts/validate` — run Gate 1 + Gate 2.
* `POST /api/recon/contracts/approve` — human approval → versioned contract.
* `GET  /api/recon/contracts/{id}` / `.../approved` — versions / latest approved.

Runtime (`routes/recon_v2.py`):

* `POST /api/recon/snapshots` — create an immutable Raw_Source/Raw_Target snapshot.
* `GET  /api/recon/snapshots[/{id}]` — list / fetch snapshot metadata.
* `POST /api/recon/runs` — execute an **approved** contract (build shadow +
  reconcile + persist).
* `GET  /api/recon/runs/{id}` / `/api/recon/results/{id}` — run / result + preview.
* `GET  /api/recon/audit` — audit log.
* `POST /api/recon/shadows/cleanup` — run TTL cleanup.

---

## Tests

`backend/recon_engine/tests/` covers: every operation, registry allow-listing,
Gate 1 (unknown op / bad field / bad params rejected), Gate 2 replay, the
executor + reconciler classifications, snapshot immutability, shadow TTL
cleanup, and the full compile→validate→approve→reconcile orchestration.

```bash
python -m pytest backend/recon_engine/tests -q
```
