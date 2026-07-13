# Design: Contract Compilation Quality + Gate 2 Diagnostics

> Status: design proposal — no code changed. Grounded in the current
> `backend/recon_engine/` implementation (compiler, executor, reconciler, Gate
> 1/2). Every recommendation below is schema-driven and domain-agnostic: it
> operates on whatever `source_schema` / `target_schema` / mapping sheet a
> caller supplies, with no field names, table names, or system names baked in.

## 0. Current state (grounding)

| Concern | Current implementation | File |
|---|---|---|
| Compiler output | `DraftContract` (business_key/compare_fields/operations only) | `models/contract.py` |
| Field resolution | Stub: `_resolve_field()` exact/case-insensitive + `technical_field` fallback. Groq: prompted, not independently verified. | `compiler/stub_compiler.py`, `compiler/groq_compiler.py` |
| Shadow build | `build_shadow_source()` applies ops in a loop; only the **final** row count/columns are observable | `engine/executor.py` |
| Gate 2 | `replay_sample()`: builds the full shadow in one shot, runs 5 fixed checks, reports pass/fail + one message each | `validation/gate2_replay.py` |
| Diagnostics shown to user | `source_sample=100 -> shadow=0 rows.` (one line) | `gate2_replay.py:112-116`, rendered flat in `TransformationSpecStep.jsx:372-377` |

The central mechanical gap: **nothing observes the pipeline between "raw sample in" and "shadow out."** Gate 2 either has the whole answer or none of it — there's no per-operation checkpoint to say *which* operation ate the rows. Fixing that is the load-bearing change everything else in this doc builds on.

One existing issue that **violates requirement A/3 today** and must be corrected as part of this work: the Groq system prompt (`groq_compiler.py`, `_SYSTEM_PREAMBLE`) currently says *"allowing for prefixes like 'I_'"* — that's an SAP/IBP-specific hint leaking into a supposedly domain-agnostic compiler. §1.2 replaces it with a generic, deterministic matching algorithm that needs no such hint.

---

## 1. Improve Contract Compilation (Requirement A)

### 1.1 Principle

A field reference is only ever schema-valid data (`source_field`/`target_field` in a `business_key`/`compare_field`, or an operation's `field`) if it can be **deterministically derived** from the real schema — never asserted by the LLM on faith. Two independent layers enforce this:

1. **Prompted, at compile time** — the LLM is instructed to resolve names itself (already partially done).
2. **Verified, deterministically, at compile time and again at Gate 1** — a shared matcher re-checks every field reference the compiler (Groq *or* stub) produced, independent of whether an LLM was involved. This is the trust-but-verify layer: prompt compliance is probabilistic, verification is not.

Layer 2 is the one that's currently missing, and it's what makes the requirement "never force-map without strong evidence" actually enforceable rather than aspirational.

### 1.2 New shared primitive: `schema_matching.py`

```python
# backend/recon_engine/schema_matching.py
"""Deterministic, domain-agnostic field-name resolution.

Used by every compiler (stub, Groq, any future one) and by Gate 1/Gate 2 to
verify compiler output. Contains no knowledge of any specific system, table,
or field — only generic string-normalisation heuristics that apply equally to
SAP, Oracle, a flat CSV, or anything else.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from enum import Enum

class MatchStrategy(str, Enum):
    EXACT = "exact"                # identical string
    CASE_INSENSITIVE = "case_insensitive"
    NORMALIZED = "normalized"      # strip non-alphanumerics, casefold
    TOKEN_SET = "token_set"        # split on non-alnum/camelCase, compare as sets
    NAMESPACE_STRIPPED = "namespace_stripped"  # generic "PREFIX_rest" vs "rest"
    NONE = "none"                  # no candidate met the confidence floor

# Confidence is fixed per strategy, not tuned per dataset — the ranking
# (exact > case-insensitive > normalized > token-set > namespace-stripped)
# is the generalizable part; the exact floats are display-only.
_CONFIDENCE = {
    MatchStrategy.EXACT: 1.0,
    MatchStrategy.CASE_INSENSITIVE: 0.9,
    MatchStrategy.NORMALIZED: 0.75,
    MatchStrategy.TOKEN_SET: 0.65,
    MatchStrategy.NAMESPACE_STRIPPED: 0.55,
    MatchStrategy.NONE: 0.0,
}
RESOLUTION_FLOOR = 0.5  # below this: unresolved, never auto-applied

def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())

def _tokens(s: str) -> frozenset[str]:
    # split on non-alnum AND camelCase boundaries: "ReqDlvQty" -> {req,dlv,qty}
    parts = re.split(r"[^a-zA-Z0-9]+", s)
    out: list[str] = []
    for p in parts:
        out.extend(re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", p))
    return frozenset(t.lower() for t in out if t)

def _strip_namespace(s: str) -> str | None:
    """Generic "NS_rest" -> "rest" split on the FIRST underscore only, if both
    a prefix and a remainder exist. No hardcoded namespace list — this is a
    structural pattern (common in many ERPs/warehouses), not a vendor rule."""
    if "_" not in s:
        return None
    _, rest = s.split("_", 1)
    return rest or None

@dataclass(frozen=True)
class FieldMatch:
    field: str              # the resolved, schema-valid name
    strategy: MatchStrategy
    confidence: float

def resolve_field(candidates: list[str], schema: list[str]) -> FieldMatch | list[FieldMatch]:
    """Try each candidate name (in priority order, e.g. [technical_field,
    source_field]) against the schema using progressively looser strategies.

    Returns:
      * a single FieldMatch if exactly one schema field clears the
        resolution floor via the *first* successful strategy tier, OR
      * a list of >=2 FieldMatch (ambiguous — caller must not guess), OR
      * [] if nothing clears the floor (unresolved).
    """
    schema_exact = set(schema)
    schema_ci = {c.lower(): c for c in schema}
    schema_norm = {_normalize(c): c for c in schema}
    schema_tokens = {c: _tokens(c) for c in schema}

    for candidate in candidates:
        if not candidate:
            continue
        if candidate in schema_exact:
            return FieldMatch(candidate, MatchStrategy.EXACT, _CONFIDENCE[MatchStrategy.EXACT])
        if candidate.lower() in schema_ci:
            m = schema_ci[candidate.lower()]
            return FieldMatch(m, MatchStrategy.CASE_INSENSITIVE, _CONFIDENCE[MatchStrategy.CASE_INSENSITIVE])
        norm = _normalize(candidate)
        if norm in schema_norm:
            m = schema_norm[norm]
            return FieldMatch(m, MatchStrategy.NORMALIZED, _CONFIDENCE[MatchStrategy.NORMALIZED])

        cand_tokens = _tokens(candidate)
        token_hits = [c for c, toks in schema_tokens.items() if toks == cand_tokens and toks]
        if len(token_hits) == 1:
            return FieldMatch(token_hits[0], MatchStrategy.TOKEN_SET, _CONFIDENCE[MatchStrategy.TOKEN_SET])
        if len(token_hits) > 1:
            return [FieldMatch(h, MatchStrategy.TOKEN_SET, _CONFIDENCE[MatchStrategy.TOKEN_SET]) for h in token_hits]

        stripped = _strip_namespace(candidate)
        if stripped and stripped in schema_norm.values():
            return FieldMatch(stripped, MatchStrategy.NAMESPACE_STRIPPED, _CONFIDENCE[MatchStrategy.NAMESPACE_STRIPPED])

    return []
```

This directly replaces the ad-hoc "ignoring prefixes like I_" instruction and the stub's bespoke `_resolve_field` with one tested, reusable, generic function. `resolve_field` never returns a match below `RESOLUTION_FLOOR` — callers treat `[]` as unresolved and a multi-element list as ambiguous, per requirement A ("preserve uncertain mappings ... rather than inventing").

### 1.3 `mapping_coverage` becomes part of the contract, not just a side note

Add a structured field to `ContractBody` (additive, optional, backward compatible):

```python
# models/contract.py additions
class MappingResolution(str, Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"

class MappingCoverageItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_index: int | None = None
    raw_source_field: str | None = None
    raw_target_field: str | None = None
    raw_technical_field: str | None = None
    resolved_source_field: str | None = None
    resolved_target_field: str | None = None
    resolution: MappingResolution
    confidence: float | None = None
    strategy: str | None = None        # MatchStrategy value, for debugging/repair
    rationale: str | None = None       # short human-readable "why"
    candidates: list[str] = Field(default_factory=list)  # for ambiguous rows

class ContractBody(BaseModel):
    ...
    mapping_coverage: list[MappingCoverageItem] = Field(default_factory=list)
```

* **Stub compiler**: already resolves fields row-by-row (post the prior fix) — change it to call `schema_matching.resolve_field()` instead of its bespoke logic, and append one `MappingCoverageItem` per row (resolved, unresolved, or ambiguous) instead of only free-text notes.
* **Groq compiler**: prompt requires one `mapping_coverage` entry per mapping-sheet row with `resolution`/`confidence`/`rationale` populated by the model's reasoning — **then** `GroqContractCompiler.compile()` re-runs `schema_matching.resolve_field()` against the model's own `raw_*` fields and **overwrites** `resolved_source_field`/`resolved_target_field`/`confidence`/`strategy` with the deterministic result, only trusting the model for `rationale` (free text) and the `unresolved`/`ambiguous` judgment call itself. Any `business_key`/`compare_field` entry whose fields don't match a `resolved` `mapping_coverage` item at the required confidence is dropped before the contract is returned, with a `notes` line explaining why (mirrors the stub's existing unresolved-row handling).

This turns "trust the LLM" into "trust the LLM's *judgment*, verify its *string matching* deterministically" — the actual generalizable fix.

---

## 2. Gate 2 Redesign

### 2.1 Architectural recommendation

Gate 2 should **stop being a one-shot black box** and become a **traced replay**: every stage of the pipeline (source → each operation → join) records its own before/after snapshot. Concretely:

1. `build_shadow_source()` gains an opt-in `trace: bool = False` parameter. When `True`, it returns a `stages: list[OperationStage]` alongside the existing `shadow_df`/`lineage`. Default `False` means **zero behavior change and zero overhead for production runs** (`run_reconciliation`) — tracing is exclusively a Gate-2/diagnostics concern.
2. Gate 2 always calls it with `trace=True` (the sample is capped at `REPLAY_SAMPLE_MAX`, ~100 rows, so the cost is negligible — see §7).
3. Gate 2 additionally runs the **real** `reconcile()` on the sample shadow vs. the target sample (not just a key-overlap check) — so its match/mismatch/missing counts on the sample structurally mirror what the production run will do, instead of a parallel, drifting implementation. This also gives `JoinImpact` for free (§2.3).
4. When the trace shows a stage collapsed to zero rows, `_localize_failure()` (§4) inspects that specific stage's operation, params, and before/after sample to rank likely causes.

### 2.2 Data structures (new module `backend/recon_engine/models/diagnostics.py`)

```python
from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field

class StageKind(str, Enum):
    SOURCE = "source"        # the initial sample, before any operation
    TRANSFORM = "transform"
    FILTER = "filter"
    AGGREGATE = "aggregate"
    JOIN = "join"             # synthetic stage added by Gate 2 after the shadow build

class OperationStage(BaseModel):
    stage_index: int
    kind: StageKind
    op: str | None = None            # operation name; None for the SOURCE stage
    field: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    rows_before: int
    rows_after: int
    rows_removed: int
    percent_removed: float
    columns_before: list[str]
    columns_after: list[str]
    sample_before: list[dict[str, Any]] = Field(default_factory=list)
    sample_after: list[dict[str, Any]] = Field(default_factory=list)

class JoinImpact(BaseModel):
    join_type: str = "full_outer"
    rows_before_source: int
    rows_before_target: int
    matched: int
    unmatched_source: int   # missing_in_target
    unmatched_target: int   # missing_in_source
    duplicate_keys_source: int
    duplicate_keys_target: int

class MappingCoverageSummary(BaseModel):
    resolved: int
    unresolved: int
    ambiguous: int
    items: list["MappingCoverageItem"]   # reuse the contract-level model

class FailureCauseCategory(str, Enum):
    INCORRECT_MAPPING = "incorrect_mapping"
    INCORRECT_JOIN = "incorrect_join"
    OVER_RESTRICTIVE_FILTER = "over_restrictive_filter"
    MISSING_SOURCE_FIELD = "missing_source_field"
    MISSING_TARGET_FIELD = "missing_target_field"
    UNSUPPORTED_TRANSFORMATION = "unsupported_transformation"
    DATA_QUALITY_ISSUE = "data_quality_issue"

class FailureCause(BaseModel):
    rank: int
    category: FailureCauseCategory
    confidence: float
    stage_index: int | None
    op: str | None
    field: str | None
    evidence: list[str]     # human-readable, evaluable-by-a-repair-agent strings

class ShadowPreview(BaseModel):
    stage_label: str
    stage_index: int
    is_final: bool
    is_fallback: bool        # True if we fell back to the last non-empty stage
    rows_shown: int
    total_rows: int
    columns: list[str]
    key_fields: list[str]
    rows: list[dict[str, Any]]
    truncated: bool
```

`Gate2Report` gains these as additive optional fields — nothing existing is removed or renamed:

```python
@dataclass
class Gate2Report:
    ok: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # NEW — all optional/empty by default:
    stage_trace: list[OperationStage] = field(default_factory=list)
    join_impact: JoinImpact | None = None
    mapping_coverage: MappingCoverageSummary | None = None
    shadow_preview: ShadowPreview | None = None
    failure_causes: list[FailureCause] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "gate": "sample_replay", "ok": self.ok,
            "checks": self.checks, "errors": self.errors, "warnings": self.warnings,
            "stage_trace": [s.model_dump(mode="json") for s in self.stage_trace],
            "join_impact": self.join_impact.model_dump(mode="json") if self.join_impact else None,
            "mapping_coverage": self.mapping_coverage.model_dump(mode="json") if self.mapping_coverage else None,
            "shadow_preview": self.shadow_preview.model_dump(mode="json") if self.shadow_preview else None,
            "failure_causes": [f.model_dump(mode="json") for f in self.failure_causes],
        }
```

Any existing consumer that only reads `ok`/`errors`/`warnings`/`checks` (today's `TransformationSpecStep.jsx`) is unaffected — the new keys are simply ignored until the frontend is updated to use them.

### 2.3 Executor instrumentation

```python
# engine/executor.py — additive change
@dataclass
class ShadowBuildResult:
    shadow_df: pd.DataFrame
    lineage: list[list[int]]
    stages: list[OperationStage] = field(default_factory=list)  # NEW, empty unless trace=True

def build_shadow_source(
    contract: TransformationContract, raw_source_df: pd.DataFrame, *, trace: bool = False,
) -> ShadowBuildResult:
    df = raw_source_df.reset_index(drop=True).copy()
    df[POS_COL] = range(len(df))
    lineage: dict[int, list[int]] = {i: [i] for i in range(len(df))}
    stages: list[OperationStage] = []

    if trace:
        stages.append(_snapshot_stage(0, StageKind.SOURCE, None, None, {}, df, df))

    for idx, op in enumerate(contract.operations, start=1):
        spec = get_operation(op.op)
        if spec.kind == OperationKind.COMPARE:
            continue
        before = df
        if spec.kind == OperationKind.AGGREGATE:
            df, lineage = _apply_aggregate(spec.func, op, df, lineage)
        else:
            df = spec.func(df, op.field, op.params)
        if trace:
            kind = {"transform": StageKind.TRANSFORM, "filter": StageKind.FILTER,
                    "aggregate": StageKind.AGGREGATE}[spec.kind.value]
            stages.append(_snapshot_stage(idx, kind, op.op, op.field, op.params, before, df))

    ...  # unchanged tail
    return ShadowBuildResult(shadow_df=final, lineage=lineage_rows, stages=stages)
```

`_snapshot_stage` computes `rows_before/after/removed/percent_removed`, `columns_before/after`, and takes `.head(N)` samples (N from `RECON_GATE2_SAMPLE_ROWS`, default small e.g. 5, independent of the shadow-preview N in §3) converted via the existing `_json_safe`-style scalar coercion (reuse the one in `mapping_sheet_parser.py`, or factor it into a shared `json_safe.py` — see §7 duplication note).

### 2.4 Filter / join impact reporting

Filter impact is just the subset of `stage_trace` where `kind == StageKind.FILTER`, formatted per the requested example:

```
Filter: exclude_value on Plant (values: ['9999'])
Rows before: 100
Rows after: 12
Removed: 88
```

This is a *view* over `stage_trace`, not new data — `describe_filter_stage(stage)` renders any filter stage generically from its `op`/`field`/`params`, so a brand-new filter operation added to the registry in the future needs no changes here.

Join impact (`JoinImpact`) comes from running the actual `reconcile()` on the sample (§2.1 point 3): `matched = len(both)`, `unmatched_source = len(source_only)`, `unmatched_target = len(target_only)`, duplicates from the existing dup-key detection in `reconciler.py:76-86` (currently computed but only surfaced as `EXCEPTION` records — Gate 2 should also read the counts directly).

---

## 3. Shadow Data Preview (Requirement C)

### 3.1 Design

`ShadowPreview` is built after the trace completes:

* If `final_rows > 0`: `stage_label="final"`, `is_fallback=False`, rows = `shadow_df.head(N)`.
* If `final_rows == 0`: walk `stage_trace` **backwards** from the last stage to find the last one with `rows_after > 0`. Use *that* stage's `sample_after` (already captured during tracing — no re-execution needed) as the preview, with `stage_label=f"before {failing_op}"` and `is_fallback=True`.
* `key_fields` = `contract.business_key` source fields (schema-driven — no assumption about which stage they survive to, since the stage's `columns_after` is checked and any key field renamed away is flagged as its own `FailureCause`, §4).
* `N` is configurable: `Settings.gate2_preview_rows`, env `RECON_GATE2_PREVIEW_ROWS`, default `10` (per requirement C).
* Rows are serialized with the same scalar-safety rules already used for mapping-sheet parsing (`NaN`→`null`, timestamps→ISO strings) so the payload is always valid JSON regardless of source dtypes — again, domain-agnostic.

### 3.2 Example output shape (matches the requested format)

```json
{
  "stage_label": "before include_value[Plnt]",
  "stage_index": 2,
  "is_final": false,
  "is_fallback": true,
  "rows_shown": 10,
  "total_rows": 47,
  "columns": ["Material", "Plnt", "Req.Dlv.Dt", "ReqDlvQty"],
  "key_fields": ["Material", "Plnt"],
  "rows": [
    {"Material": "100023", "Plnt": "1000", "Req.Dlv.Dt": "2026-01-04", "ReqDlvQty": 12},
    { "...": "..." }
  ],
  "truncated": true
}
```

---

## 4. Failure Localization (Requirement D)

### 4.1 Algorithm (generic, evidence-based, no dataset-specific rules)

`_localize_failure(stage_trace, contract, source_schema, target_schema, mapping_coverage)`:

1. **Find the collapse point**: the first stage in `stage_trace` where `rows_before > 0 and rows_after == 0`. If none (rows never hit zero mid-pipeline but the *join* produced zero matches), the collapse point is the synthetic `JOIN` stage instead.
2. **Classify by structural evidence**, in priority order (each rule only fires on structural facts already computed — no heuristics tied to any field name):

   | Rule | Evidence checked | Category |
   |---|---|---|
   | A resolved `mapping_coverage` item's `resolved_source_field` is absent from `columns_before` of the collapse stage | field genuinely doesn't exist at that point in the pipeline | `missing_source_field` |
   | Same, for `resolved_target_field` vs. `target_schema` | | `missing_target_field` |
   | Collapse stage `kind == FILTER` | operation is a filter (`reject_null`/`exclude_value`/`include_value`) | `over_restrictive_filter` |
   | Collapse stage `kind == JOIN` and `duplicate_keys_*` ≈ 0 and `unmatched_source`/`unmatched_target` both high | keys don't overlap despite no dupes | `incorrect_join` (usually a business_key mismatch) |
   | Collapse stage `kind == JOIN` and one side's key set is a case/whitespace/format variant of the other (checked via the same `schema_matching._normalize` on the *values*, not just field names) | near-miss key overlap after normalization | `incorrect_mapping` |
   | Collapse stage `kind in {TRANSFORM, AGGREGATE}` and `sample_before` had non-null values that became null/NaN in `sample_after` for the op's field | operation actively destroyed data it was given | `unsupported_transformation` |
   | None of the above, but `null_fraction` of the *input* sample for the relevant field was already high pre-pipeline | garbage in, garbage out | `data_quality_issue` |
   | Fallback (multiple structural signals present) | | lowest-confidence duplicate of the above, kept for transparency |

3. Each match becomes a `FailureCause` with `confidence` derived from how many independent evidence lines support it (more corroborating checks → higher confidence), `evidence: list[str]` containing the literal facts observed (e.g. `"Filter 'include_value' on field 'Plnt' with values=['9999'] removed 88 of 100 rows (88%)."`), and `rank` by confidence descending.
4. Multiple causes can co-occur (e.g. a filter *and* a join mismatch) — return the ranked list, not a single verdict, matching requirement D ("ranked list of likely causes with supporting evidence").

### 4.2 Example payload

```json
"failure_causes": [
  {
    "rank": 1,
    "category": "over_restrictive_filter",
    "confidence": 0.9,
    "stage_index": 2,
    "op": "include_value",
    "field": "Plnt",
    "evidence": [
      "Filter 'include_value' on field 'Plnt' with values=['9999'] removed 88 of 100 rows (88%).",
      "Distinct values of 'Plnt' present before the filter: ['1000', '1010', '9999', '2000'] — only 1 of 4 survives."
    ]
  },
  {
    "rank": 2,
    "category": "incorrect_mapping",
    "confidence": 0.4,
    "stage_index": null,
    "op": null,
    "field": "Req.Dlv.Dt",
    "evidence": [
      "mapping_coverage marks 'Req.Dlv.Dt' -> 'KEYFIGUREDATE' as resolved via NORMALIZED strategy (confidence 0.75), the lowest tier that still auto-applies."
    ]
  }
]
```

---

## 5. Contract Self-Repair Preparation (Requirement E)

The design above already satisfies this by construction:

* **Structured**: every payload is a Pydantic model, not free text — `model_dump(mode="json")` gives a stable, versioned schema.
* **Machine-readable**: `FailureCause.category` is a closed enum a repair agent can switch on; `evidence` strings are for humans, `stage_index`/`op`/`field` are for machines.
* **Stage-aware**: `stage_trace` gives a repair workflow the exact operation index to mutate or remove.
* **Operation-aware**: every stage carries `op` + `params`, so a repair proposal can be expressed as "replace stage 2's `params.values` with X" without re-deriving what stage 2 even is.

A future auto-repair loop is then: `Gate2Report.failure_causes[0]` → look up `stage_index` in `stage_trace` → propose a contract edit (e.g. drop the over-restrictive filter, or re-run compilation with that `mapping_coverage` item forced to `unresolved` so the LLM is asked again with that specific ambiguity flagged) → re-run Gate 1 + Gate 2 → compare `shadow_preview.total_rows` before/after. Nothing in this doc's data structures needs to change to support that later — it's why the schema favors explicit indices/enums over prose everywhere.

---

## 6. Example end-to-end diagnostic payload

Full `/api/recon/contracts/validate` response for a contract whose Gate 2 sample collapsed to zero rows at an over-restrictive filter (illustrative field names only — the shape is what matters):

```json
{
  "ok": false,
  "gate1": { "gate": "structural", "ok": true, "errors": [] },
  "gate2": {
    "gate": "sample_replay",
    "ok": false,
    "checks": [
      {"name": "row_count", "ok": false, "message": "source_sample=100 -> shadow=0 rows."}
    ],
    "errors": ["row_count: source_sample=100 -> shadow=0 rows."],
    "warnings": [],
    "stage_trace": [
      {"stage_index": 0, "kind": "source", "op": null, "field": null, "params": {},
       "rows_before": 100, "rows_after": 100, "rows_removed": 0, "percent_removed": 0.0,
       "columns_before": ["Material", "Plnt", "Req.Dlv.Dt", "ReqDlvQty"],
       "columns_after": ["Material", "Plnt", "Req.Dlv.Dt", "ReqDlvQty"],
       "sample_before": [], "sample_after": [ /* 5 sample rows */ ]},
      {"stage_index": 1, "kind": "transform", "op": "trim_string", "field": "Material", "params": {},
       "rows_before": 100, "rows_after": 100, "rows_removed": 0, "percent_removed": 0.0,
       "columns_before": ["Material","Plnt","Req.Dlv.Dt","ReqDlvQty"],
       "columns_after": ["Material","Plnt","Req.Dlv.Dt","ReqDlvQty"],
       "sample_before": [], "sample_after": []},
      {"stage_index": 2, "kind": "filter", "op": "include_value", "field": "Plnt",
       "params": {"values": ["9999"]},
       "rows_before": 100, "rows_after": 0, "rows_removed": 100, "percent_removed": 100.0,
       "columns_before": ["Material","Plnt","Req.Dlv.Dt","ReqDlvQty"],
       "columns_after": ["Material","Plnt","Req.Dlv.Dt","ReqDlvQty"],
       "sample_before": [ /* 5 rows, Plnt mostly != 9999 */ ], "sample_after": []}
    ],
    "join_impact": null,
    "mapping_coverage": {
      "resolved": 3, "unresolved": 1, "ambiguous": 0,
      "items": [ /* MappingCoverageItem[] */ ]
    },
    "shadow_preview": {
      "stage_label": "before include_value[Plnt]", "stage_index": 2,
      "is_final": false, "is_fallback": true,
      "rows_shown": 10, "total_rows": 100,
      "columns": ["Material","Plnt","Req.Dlv.Dt","ReqDlvQty"],
      "key_fields": ["Material","Plnt"],
      "rows": [ /* 10 rows */ ],
      "truncated": true
    },
    "failure_causes": [
      {"rank": 1, "category": "over_restrictive_filter", "confidence": 0.9,
       "stage_index": 2, "op": "include_value", "field": "Plnt",
       "evidence": [
         "Filter 'include_value' on field 'Plnt' with values=['9999'] removed 100 of 100 rows (100%).",
         "Distinct values of 'Plnt' before the filter: ['1000','1010','2000'] — none match ['9999']."
       ]}
    ]
  }
}
```

---

## 7. Backward-compatible implementation plan

| Phase | Change | Compatibility impact |
|---|---|---|
| 1 | Add `schema_matching.py` + unit tests | None — new module, unused until wired in |
| 2 | Add `models/diagnostics.py` (`OperationStage`, `JoinImpact`, `FailureCause`, `ShadowPreview`) + `MappingCoverageItem`/`MappingResolution` in `models/contract.py` | None — new/additive fields only |
| 3 | Instrument `executor.build_shadow_source(..., trace: bool = False)` | None — default `False`, existing callers (`run_reconciliation`) untouched |
| 4 | Rewrite `stub_compiler.py` to use `schema_matching.resolve_field()` + emit `mapping_coverage` | Existing tests (`test_stub_compiler_*`) keep passing — same resolution semantics, now shared/tested code instead of bespoke |
| 5 | Update Groq prompt (`_SYSTEM_PREAMBLE`) to require `mapping_coverage` in output, remove the "I_" hardcoded hint; add deterministic re-verification pass in `GroqContractCompiler.compile()` | Additive to `ContractBody`; existing Groq drafts without `mapping_coverage` still validate (field defaults to `[]`) |
| 6 | Rewrite `validation/gate2_replay.py`: call `build_shadow_source(trace=True)`, call real `reconcile()` on the sample, populate the new `Gate2Report` fields, run `_localize_failure()` | `Gate2Report.as_dict()` keeps every existing key; new keys added. Existing frontend code paths (`gate2.errors`, `gate2.warnings`, `gate2.ok`) unaffected |
| 7 | `routes/contracts.py` `/contracts/validate` — no signature change; response body just carries the richer `gate2` dict | None |
| 8 (frontend, separate PR) | New `Gate2DiagnosticsPanel` component rendering `stage_trace` as a waterfall, `shadow_preview` as a table, `failure_causes` as a ranked list — reusing the existing table patterns already in `TransformationPreviewPanel.jsx` (`ModifiedColumnsTable`, `RowDiffsTable`) | Purely additive; old flat error/warning rendering can stay as a fallback for gate2 payloads that predate this change |

Each phase ships independently and is tested before the next starts; nothing requires a coordinated big-bang deploy.

---

## 8. Risks and performance considerations

* **Sample size bounds the cost.** Tracing only ever runs against `REPLAY_SAMPLE_MAX` rows (currently 100, `config.py`) — even with a snapshot per operation, worst case is `num_operations × 100 rows × few columns`, negligible. Production `run_reconciliation` never sets `trace=True`, so full-data runs see zero added cost.
* **Payload size.** `stage_trace[*].sample_before/after` should cap at a small fixed row count (e.g. 5, separate constant from the shadow-preview's 10) to keep `/contracts/validate` responses bounded regardless of how many operations a contract has.
* **PII/sensitive data in diagnostics.** Samples now appear in logs/API responses more richly than today's `source_sample=100` line. If source data can be sensitive, this needs the same access controls as the existing sample-upload flow already has — no new exposure surface is created (Gate 2 already receives the full sample), but the *diagnostic payload* now persists more of it further downstream (e.g. into audit records, if those are later extended to store `Gate2Report`). Worth an explicit decision on retention.
* **Duplicated JSON-safety logic.** `mapping_sheet_parser._json_safe` and the new stage/preview serializers need the same NaN/Timestamp handling. Recommend factoring `_json_safe` into a shared `backend/recon_engine/json_safe.py` used by both, rather than copy-pasting (avoids drift when a new dtype shows up).
* **`schema_matching` false positives.** Token-set matching (`{req,dlv,qty}`) is looser than exact match and could theoretically conflate two unrelated fields that happen to share tokens. Mitigated by: (a) it's the third-lowest confidence tier, (b) any ambiguous multi-match is surfaced, never silently picked, and (c) Gate 1 still hard-blocks any field not literally in the schema regardless of how it was chosen.
* **Real `reconcile()` inside Gate 2** changes Gate 2's cost from O(build shadow) to O(build shadow + full-outer-join on ≤100+100 rows) — still trivial, but it does mean Gate 2 now depends on `reconciler.py`, a dependency direction that didn't exist before (`gate2_replay.py` currently doesn't import `reconciler`). No cycle results (`reconciler.py` doesn't import `validation/`), but worth noting as a new coupling.
