// Auto-run mode: the unattended path from "all three inputs present" to a
// rendered Results screen, plus the gate that decides whether that path is
// allowed to approve its own compiled chain.
//
// This exists alongside — never instead of — the manual approve flow on the
// Mapping step. Auto mode skips the CLICK, never a CHECK: it runs the same
// endpoints in the same order the human-driven path runs (infer field mapping
// -> resolve the mapping sheet into a chain -> build the draft -> Gate 1/2
// static validation -> approve -> snapshot -> run), and refuses to approve
// anything it cannot fully account for. When the gate refuses, the compiled
// work is kept as a working draft and the user finishes it by hand on the
// Mapping step — that is the fallback, not an error state.
import api from "../../services/api";
import { WizardActions } from "../context/wizardReducer";
import {
  appendDatasetSide,
  cleanAggregationRules,
  gate2SampleRows,
  mergeGeneratedMapping,
  rebuildMapping,
} from "./payload";
import { operationsToSteps, serializeOperations } from "./transformationsModel";
import { createBothSnapshots, identicalDatasetReason, runContractReconciliation } from "./reconRun";

// Stable identifiers for every auto-approve condition. A blocked auto-run
// reports which of these failed, by name — never a generic "validation failed"
// — because the whole point of stopping is telling the user what to go fix.
export const GateCheck = {
  FIELD_BINDING: "field_binding",
  HEADER_BINDING_PENDING: "header_binding_pending",
  UNSUPPORTED_PRIMITIVE: "unsupported_primitive",
  REQUIRES_VALUE_PAIRING: "requires_value_pairing",
  KEY_COMPARE_PROVENANCE: "key_compare_provenance",
  STATIC_VALIDATION: "static_validation",
  EMPTY_NODE: "empty_node",
};

// The stages runAutoPipeline walks, in order — the "steps 1–7" both the status
// banner and the manual re-run control count against.
export const STAGE_ORDER = ["mapping", "resolve", "snapshots", "validate", "gate", "approve", "run"];

export const GATE_CHECK_LABELS = {
  [GateCheck.FIELD_BINDING]: "Field binding",
  [GateCheck.HEADER_BINDING_PENDING]: "Header binding",
  [GateCheck.UNSUPPORTED_PRIMITIVE]: "Unsupported primitive",
  [GateCheck.REQUIRES_VALUE_PAIRING]: "Requires value pairing",
  [GateCheck.KEY_COMPARE_PROVENANCE]: "Key/Compare confirmation",
  [GateCheck.STATIC_VALIDATION]: "Static validation",
  [GateCheck.EMPTY_NODE]: "Empty result",
};

// Provenance values that mean a Key/Compare role was NOT invented by the LLM
// for this run: a human typed/edited it, or it was reused from the validated
// attribute library (which only ever holds mappings a human already approved on
// a previous run). Anything else — "azure_foundry", "generated", missing — is
// an LLM proposal that no human has confirmed.
const CONFIRMED_PROVENANCE = new Set(["library", "user-edited", "user-added"]);

function failure(check, detail) {
  return { check, label: GATE_CHECK_LABELS[check] ?? check, detail };
}

// ── the gate ────────────────────────────────────────────────────────────────
// Pure: takes everything already fetched and decides eligibility. Returns
// `{ eligible, failures }`. Auto-approval requires ALL conditions to hold — a
// partial or uncertain chain is never auto-approved.
export function evaluateAutoApproveGate({
  mapping,
  mappingResolution,
  sourceColumns = [],
  targetColumns = [],
  validation,
  chainRowCounts,
}) {
  const failures = [];
  const srcSet = new Set(sourceColumns);
  const tgtSet = new Set(targetColumns);

  // 1. Every declared field resolves to a bound source/target column. Rows the
  //    mapping table declares must name columns that actually exist on both
  //    sides — a half-bound row silently drops out of rebuildMapping(), taking
  //    a comparison the user expected with it.
  const rows = mapping?.display ?? [];
  const unbound = [];
  for (const row of rows) {
    if (!row.source_col && !row.target_col) continue;
    if (!row.source_col || !srcSet.has(row.source_col)) {
      unbound.push(`${row.source_col || "(no source column)"} (source)`);
    } else if (!row.target_col || !tgtSet.has(row.target_col)) {
      unbound.push(`${row.target_col || "(no target column)"} (target)`);
    }
  }
  if (unbound.length > 0) {
    failures.push(
      failure(
        GateCheck.FIELD_BINDING,
        `${unbound.length} declared field${unbound.length === 1 ? "" : "s"} did not bind to a column in the uploaded data: ${unbound.join(", ")}.`,
      ),
    );
  }
  if (rows.length > 0 && (mapping?.mapping?.key_fields?.length ?? 0) === 0) {
    failures.push(
      failure(GateCheck.FIELD_BINDING, "No Key field is confirmed — at least one is required to reconcile."),
    );
  }

  // 2. No field left pending_confirmation from header binding.
  const pending = mappingResolution?.pending_confirmation ?? [];
  if (pending.length > 0) {
    failures.push(
      failure(
        GateCheck.HEADER_BINDING_PENDING,
        `${pending.length} field${pending.length === 1 ? "" : "s"} from the mapping sheet could not be bound: ${pending
          .map((p) => `${p.field}${p.reason ? ` — ${p.reason}` : ""}`)
          .join("; ")}.`,
      ),
    );
  }

  // 3. No node flagged "unsupported primitive" or "requires value pairing".
  const proposed = mappingResolution?.proposed_operations ?? [];
  if (proposed.length > 0) {
    failures.push(
      failure(
        GateCheck.UNSUPPORTED_PRIMITIVE,
        `${proposed.length} step${proposed.length === 1 ? " needs" : "s need"} an operation this engine does not implement yet: ${proposed
          .map((p) => `${p.name} (${p.kind})`)
          .join(", ")}.`,
      ),
    );
  }
  const crosswalk = mappingResolution?.requires_value_pairing ?? [];
  if (crosswalk.length > 0) {
    failures.push(
      failure(
        GateCheck.REQUIRES_VALUE_PAIRING,
        `${crosswalk.length} field${crosswalk.length === 1 ? "" : "s"} need value-level pairing, which this deploy does not run: ${crosswalk
          .map((f) => f.source_column)
          .join(", ")}. Map them with a transformation step instead.`,
      ),
    );
  }

  // 4. Key/Compare must stay human-confirmable. An LLM may PROPOSE the role
  //    split, but the business key it proposed must not execute without a human
  //    having seen it — so a run whose keys came straight from the model stops
  //    here and asks for the one click that makes a person the owner of it.
  const llmOwned = rows
    .filter((r) => r.source_col && r.target_col)
    .filter((r) => !CONFIRMED_PROVENANCE.has(r.provenance))
    .map((r) => `${r.source_col} → ${r.target_col}`);
  if (llmOwned.length > 0) {
    failures.push(
      failure(
        GateCheck.KEY_COMPARE_PROVENANCE,
        `${llmOwned.length} Key/Compare assignment${llmOwned.length === 1 ? " was" : "s were"} proposed by the AI and not yet confirmed by a person: ${llmOwned.join(", ")}. Review the Key/Compare column and approve to confirm them.`,
      ),
    );
  }

  // 5. Static validation — the same Gate 1 / Gate 2 report manual mode requires
  //    before its own approve call. Surfaced by gate name, not as a blob.
  if (validation && !validation.ok) {
    const g1 = validation.gate1?.errors ?? [];
    const g2 = (validation.gate2?.errors ?? []).filter((e) => e !== "skipped: gate 1 failed");
    const named = (validation.gate2?.checks ?? [])
      .filter((c) => c && c.ok === false)
      .map((c) => `${c.name}: ${c.message}`);
    const detail = [...g1, ...g2, ...named];
    failures.push(
      failure(
        GateCheck.STATIC_VALIDATION,
        detail.length > 0 ? detail.join(" ") : "The draft did not pass Gate 1/Gate 2 validation.",
      ),
    );
  }

  // 6. Shadow preview row count > 0 for every node.
  const emptyNodes = chainRowCounts?.empty_nodes ?? [];
  if (emptyNodes.length > 0) {
    failures.push(
      failure(
        GateCheck.EMPTY_NODE,
        `${emptyNodes.length} step${emptyNodes.length === 1 ? "" : "s"} produced no rows: ${emptyNodes
          .map((n) =>
            n.error
              ? `step ${n.step_index + 1} (${n.op}) failed — ${n.error}`
              : `step ${n.step_index + 1} (${n.op}${n.field ? ` on ${n.field}` : ""}) left 0 of ${n.rows_in} rows`,
          )
          .join("; ")}.`,
      ),
    );
  }

  return { eligible: failures.length === 0, failures };
}

// ── the pipeline ────────────────────────────────────────────────────────────

// Identifies the current (mapping sheet, source, target) triple. A change to
// any slot changes this, which is what re-arms the auto-run — and what makes a
// completed run stay completed instead of firing again on every render.
export function inputSignature(state) {
  const sheet = state.transformationSpec?.parsedMappingSheet;
  const src = state.source?.dataset;
  const tgt = state.target?.dataset;
  if (!sheet || !src || !tgt) return null;
  return [
    sheet.sheet_name ?? "",
    sheet.row_count ?? "",
    src.datasetId ?? src.fetchedAt ?? src.filename ?? "",
    src.rowCount ?? "",
    tgt.datasetId ?? tgt.fetchedAt ?? tgt.filename ?? "",
    tgt.rowCount ?? "",
  ].join("::");
}

export function hasAllThreeInputs(state) {
  return Boolean(
    state.transformationSpec?.parsedMappingSheet && state.source?.dataset && state.target?.dataset,
  );
}

// Runs the whole happy path. Resolves to one of:
//   { outcome: "reconciled", result }        — approved and ran; land on Results
//   { outcome: "blocked", failures, stage }  — gate refused; manual approve required
// and throws only on a genuine transport/engine error (caller reports it and
// falls back to manual).
//
// `onStage` reports progress for the UI. Everything it computes is dispatched
// into the same state slots the manual flow writes, so a blocked run leaves the
// Mapping step populated and ready to finish by hand.
export async function runAutoPipeline({ state, dispatch, onStage = () => {} }) {
  const { source, target, comparisonType, transformationSpec } = state;
  const sourceColumns = source.dataset?.columns ?? [];
  const targetColumns = target.dataset?.columns ?? [];

  const identical = identicalDatasetReason(source, target);
  if (identical) {
    throw new Error(
      `Source and target must be different datasets — ${identical}. Re-upload the correct file for one side.`,
    );
  }

  // All three inputs are present, so the three steps that collect them are
  // complete by definition — mark them now rather than at the end. This unlocks
  // the Mapping step, which is where a BLOCKED run has to be able to land so
  // the user can read the failing checks and approve manually. Results stays
  // locked until something is actually approved.
  ["comparisonType", "source", "target"].forEach((step) =>
    dispatch({ type: WizardActions.COMPLETE_STEP, step }),
  );

  // ── 1. field mapping (Key/Compare proposal) ───────────────────────────────
  onStage("mapping");
  const inferForm = new FormData();
  if (!appendDatasetSide(inferForm, "source", source) || !appendDatasetSide(inferForm, "target", target)) {
    throw new Error("Source or target data is no longer available. Re-upload it to continue.");
  }
  inferForm.append("source_connector", source.kind ?? "excel");
  inferForm.append("target_connector", target.kind ?? "excel");
  inferForm.append("comparison_type", comparisonType?.id ?? "custom");
  inferForm.append("source_columns", JSON.stringify(sourceColumns));
  inferForm.append("target_columns", JSON.stringify(targetColumns));

  const inferRes = await api.post("/api/recon/mapping/infer", inferForm);
  const inferData = inferRes.data ?? {};
  // Same rule Regenerate follows on the Mapping step: rows a person edited or
  // added are kept verbatim and only generated rows are refreshed. On the first
  // pass there is no previous mapping, so this is the inference unchanged; on a
  // re-run (RESTART_AUTO_RUN keeps the mapping for exactly this) it is what
  // stops the replay from overwriting hand-confirmed Key/Compare assignments.
  const display = mergeGeneratedMapping(
    state.transformationSpec?.mapping?.display,
    inferData.display ?? [],
  );
  const mapping = {
    display,
    mapping: rebuildMapping(display, inferData.mapping?.options),
    origin: {
      source: inferData.source ?? null,
      provider: inferData.provider ?? null,
      version: inferData.library_version ?? null,
      confidence: inferData.confidence ?? null,
    },
  };
  dispatch({ type: WizardActions.SET_TRANSFORMATION_MAPPING, mapping });

  // ── 2. mapping sheet -> compiled chain + header bindings ──────────────────
  onStage("resolve");
  const resolveRes = await api.post("/api/recon/mapping-resolution/resolve", {
    mapping_sheet: transformationSpec.parsedMappingSheet,
    source_columns: sourceColumns,
    target_columns: targetColumns,
  });
  const mappingResolution = resolveRes.data ?? null;

  // Seed the editor only when it is still empty — a re-run must never silently
  // overwrite steps a human authored (same rule the Mapping step applies).
  let steps = transformationSpec.transformations ?? [];
  if (steps.length === 0 && (mappingResolution?.operations ?? []).length > 0) {
    const catalogueRes = await api.get("/api/recon/operations");
    const catalogue = (catalogueRes.data?.operations ?? []).filter((o) => o.kind !== "compare");
    steps = operationsToSteps(mappingResolution.operations, catalogue);
    dispatch({ type: WizardActions.SET_TRANSFORMATIONS, transformations: steps });
  }
  dispatch({ type: WizardActions.SET_MAPPING_RESOLUTION, mappingResolution });

  // ── 3. the draft this run would execute ───────────────────────────────────
  const draft = {
    comparison_type: comparisonType?.id ?? "custom",
    source_type: source.kind ?? "excel",
    target_type: target.kind ?? "excel",
    operations: serializeOperations(steps),
    aggregation_rules: cleanAggregationRules(transformationSpec.aggregationRules),
    business_key: (mapping.mapping.key_fields ?? []).map((f) => ({
      source_field: f.source_col,
      target_field: f.target_col,
    })),
    compare_fields: (mapping.mapping.compare_fields ?? []).map((f) => ({
      source_field: f.source_col,
      target_field: f.target_col,
    })),
    value_mappings: [],
    source_schema: sourceColumns,
    target_schema: targetColumns,
    options: { case_insensitive: true, trim_whitespace: true },
    compiler: "transformations",
  };
  dispatch({ type: WizardActions.SET_DRAFT_CONTRACT, draftContract: draft });

  // Cheap, response-derived checks first: if the chain is already known to be
  // incomplete there is no point paying for snapshots and a replay.
  const preflight = evaluateAutoApproveGate({
    mapping,
    mappingResolution,
    sourceColumns,
    targetColumns,
  });
  if (!preflight.eligible) {
    return { outcome: "blocked", stage: "resolve", failures: preflight.failures };
  }

  // ── 4. snapshots (reused by the run, and by a later manual approve) ───────
  onStage("snapshots");
  const { sourceSnapshot, targetSnapshot } = await createBothSnapshots(source, target, comparisonType);
  dispatch({
    type: WizardActions.SET_SHADOW_SNAPSHOTS,
    sourceSnapshotId: sourceSnapshot.snapshot_id,
    targetSnapshotId: targetSnapshot.snapshot_id,
  });

  // ── 5. static validation — identical to manual mode, unchanged ────────────
  onStage("validate");
  const [sourceSample, targetSample] = await Promise.all([
    gate2SampleRows(source),
    gate2SampleRows(target),
  ]);
  const validationRes = await api.post("/api/recon/contracts/validate", {
    draft,
    source_columns: sourceColumns,
    target_columns: targetColumns,
    source_sample: sourceSample,
    target_sample: targetSample,
    actor: "wizard-auto",
  });
  const validation = validationRes.data;
  dispatch({ type: WizardActions.SET_CONTRACT_VALIDATION, validation });

  if (!validation?.ok) {
    const { failures } = evaluateAutoApproveGate({
      mapping,
      mappingResolution,
      sourceColumns,
      targetColumns,
      validation,
    });
    return { outcome: "blocked", stage: "validate", failures };
  }

  // ── 6. per-node row counts against the FULL source frame ──────────────────
  onStage("gate");
  const countsRes = await api.post("/api/recon/chain-row-counts", {
    draft,
    source_snapshot_id: sourceSnapshot.snapshot_id,
    actor: "wizard-auto",
  });
  const chainRowCounts = countsRes.data ?? null;

  const gate = evaluateAutoApproveGate({
    mapping,
    mappingResolution,
    sourceColumns,
    targetColumns,
    validation,
    chainRowCounts,
  });
  if (!gate.eligible) {
    return { outcome: "blocked", stage: "gate", failures: gate.failures };
  }

  // ── 7. auto-approve, then execute + reconcile with no extra click ─────────
  onStage("approve");
  const approveRes = await api.post("/api/recon/contracts/approve", {
    draft,
    approved_by: "wizard-auto",
  });
  const contract = approveRes.data?.contract;
  dispatch({ type: WizardActions.SET_APPROVED_CONTRACT, contract });
  dispatch({ type: WizardActions.SET_APPROVAL_MODE, approvalMode: "auto" });

  // SET_APPROVED_CONTRACT re-locks Results (a fresh approval normally wants a
  // fresh review). Auto mode's review IS the gate above, so complete the
  // Mapping step to unlock it — the same transition Continue would have made.
  dispatch({ type: WizardActions.COMPLETE_STEP, step: "transformationSpec" });

  onStage("run");
  const result = await runContractReconciliation({
    contract,
    sourceSnapshotId: sourceSnapshot.snapshot_id,
    targetSnapshotId: targetSnapshot.snapshot_id,
    expectedShadowFingerprint: null,
    anchorDate: transformationSpec.anchorDate,
  });
  dispatch({
    type: WizardActions.SET_RECONCILIATION_RESULT,
    result: {
      ...result,
      source_snapshot: result.source_snapshot ?? sourceSnapshot,
      target_snapshot: result.target_snapshot ?? targetSnapshot,
    },
  });
  dispatch({ type: WizardActions.COMPLETE_STEP, step: "reconciliation" });

  return { outcome: "reconciled", result };
}
