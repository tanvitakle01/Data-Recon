import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../../services/api";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import StepShell from "../components/StepShell";
import { getVisibleSteps, getStepByKey } from "./stepConfig";
import { liveKindForRole } from "../lib/connectorOptions";
import {
  describeEntitySource,
  effectiveEntityJoin,
  freeTextEntityJoin,
  joinSummary,
  sheetEntityJoin,
} from "../lib/entityJoinSpec";
import { Badge, Select, Button, Alert } from "@bristlecone/canopy";
import { Upload, FileSpreadsheet, X, Loader2, Check, AlertTriangle, Circle } from "lucide-react";

// Elapsed-time display for Auto mode: purely client-side (no backend job
// status is polled fast enough to drive a smooth tick) — starts the moment
// Auto is clicked, freezes at the last tick once the run reaches a terminal
// state.
function formatElapsed(ms) {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

const AUTO_STEP_LABELS = {
  select_source: "Selecting source system…",
  import_source: "Importing source data…",
  select_target: "Selecting target system…",
  import_target: "Importing target data…",
  identify_candidate_keys: "Identifying candidate business keys (AI)…",
  extract_unique_keys: "Identifying unique key values…",
  pair_values: "Running AI value-pairing…",
  compile_and_run: "Running reconciliation…",
};

// Only Sales Order History is offered for now. Additional comparison types
// will be added here (or sourced from /api/comparison-types) as their
// transformation logic is built out.
const COMPARISON_TYPES = [{ id: "salesorderhistory", label: "Sales Order History" }];

const SHEET_ACCEPT = ".xlsx,.xls,.csv";

// ── Upload (empty state) ──────────────────────────────────────────────────
// The primary action on this step: a clean dropzone card, drag/drop or a
// single prominent button. Nothing else is on screen until a file lands.
function UploadDropzone({ onPick, onDropFile, loading }) {
  const [dragOver, setDragOver] = useState(false);
  return (
    <div
      className={`wizard-upload-card ${dragOver ? "is-dragover" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        const file = e.dataTransfer.files?.[0];
        if (file) onDropFile(file);
      }}
    >
      <Upload className="wizard-upload-card__icon" aria-hidden />
      <p className="wizard-upload-card__title">Upload your mapping sheet</p>
      <p className="wizard-upload-card__subtitle">
        Drag &amp; drop a file here, or choose one (.xlsx, .xls, .csv)
      </p>
      <Button variant="primary" onClick={onPick} loading={loading} disabled={loading}>
        {loading ? "Reading sheet…" : "Upload Mapping Sheet"}
      </Button>
    </div>
  );
}

// ── Detection Details (collapsed accordion content) ──────────────────────
// Everything the compact summary leaves out: confidence, evidence, full
// field lists, resolved/unresolved/ambiguous entities, join defaults vs
// stated, planning-area provenance, detection method, warnings. One side's
// section covers BOTH the connector identification and its entity/join —
// there is exactly one detailed place to look, not several.
function SideDetail({ title, side, spec, overridesSheet }) {
  if (!side) return null;
  const confident = Boolean(side.kind);
  const join = spec ? joinSummary(spec) : null;
  const provenance = spec ? describeEntitySource(spec) : "";

  return (
    <div className="wizard-detail-side">
      <div className="wizard-detail-side__head">
        <span className="wizard-detail-side__title">{title}</span>
        {confident ? (
          <Badge variant="success" dot>
            {side.label}
          </Badge>
        ) : (
          <Badge variant="warning">Not identified</Badge>
        )}
        {side.confidence && confident && (
          <span className="wizard-detail-muted">{side.confidence} confidence</span>
        )}
      </div>
      {side.evidence && <p className="wizard-detail-muted">{side.evidence}</p>}
      {side.fields?.length > 0 && (
        <p className="wizard-detail-muted">Fields: {side.fields.join(", ")}</p>
      )}

      <dl className="wizard-detail-dl">
        <dt>Entities</dt>
        <dd>
          {spec && spec.entities.length > 0 ? (
            spec.entities.map((e, i) => (
              <span key={e} className="wizard-detail-chip">
                {e}
                {i === 0 && spec.entities.length > 1 ? " (primary)" : ""}
              </span>
            ))
          ) : (
            <span className="wizard-detail-muted">None identified</span>
          )}
        </dd>

        {spec?.unresolved?.length > 0 && (
          <>
            <dt>Not matched</dt>
            <dd className="wizard-detail-warn">
              {spec.unresolved.join(", ")} — not in this connector's live entity list.
            </dd>
          </>
        )}

        {spec?.ambiguous?.length > 0 && (
          <>
            <dt>Ambiguous</dt>
            <dd className="wizard-detail-warn">
              Matches {spec.ambiguous.length} entities equally (
              {spec.ambiguous.slice(0, 4).join(", ")}
              {spec.ambiguous.length > 4 ? "…" : ""}) — name the planning area in Additional Instructions.
            </dd>
          </>
        )}

        {spec?.planningArea && (
          <>
            <dt>Planning area</dt>
            <dd>
              <span className="wizard-detail-chip">{spec.planningArea}</span>
            </dd>
          </>
        )}

        {spec && (
          <>
            <dt>Join</dt>
            <dd>
              {spec.entities.length < 2 ? (
                <span className="wizard-detail-muted">Single entity — no join.</span>
              ) : (
                <>
                  {join.typeLabel} join on {join.keysLabel}
                  {(!join.typeStated || !join.keysStated) && (
                    <span className="wizard-detail-muted">
                      {" "}
                      (
                      {!join.typeStated && !join.keysStated
                        ? "default — not specified"
                        : !join.typeStated
                          ? "join type is the default"
                          : "keys are the default"}
                      )
                    </span>
                  )}
                </>
              )}
            </dd>
          </>
        )}

        {spec && (spec.entities.length > 0 || spec.ambiguous.length > 0) && (
          <>
            <dt>Source</dt>
            <dd>
              {provenance || (spec.origin === "freeText" ? "Your typed instruction" : "The mapping sheet")}
              {overridesSheet && " — overrides the mapping sheet"}
              {spec.entityEvidence && <span className="wizard-detail-muted"> · {spec.entityEvidence}</span>}
            </dd>
          </>
        )}
      </dl>
    </div>
  );
}

function DetectionDetails({ state, identification }) {
  const sourceSpec = effectiveEntityJoin(state, "source");
  const targetSpec = effectiveEntityJoin(state, "target");
  const sourceOverrides = Boolean(
    freeTextEntityJoin(state.entityJoin, "source") && sheetEntityJoin(identification, "source")
  );
  const targetOverrides = Boolean(
    freeTextEntityJoin(state.entityJoin, "target") && sheetEntityJoin(identification, "target")
  );
  const warnings = [
    ...(identification.warnings ?? []),
    ...(state.entityJoin?.source?.parsed?.warnings ?? []),
    ...(state.entityJoin?.target?.parsed?.warnings ?? []),
  ];

  return (
    <div className="wizard-detection-details">
      <SideDetail title="Source" side={identification.source} spec={sourceSpec} overridesSheet={sourceOverrides} />
      <SideDetail title="Target" side={identification.target} spec={targetSpec} overridesSheet={targetOverrides} />
      {identification.provider && (
        <p className="wizard-detail-muted">Detection method: {identification.provider}</p>
      )}
      {warnings.map((w, i) => (
        <Alert variant="warning" key={i} style={{ marginTop: 6 }}>
          {w}
        </Alert>
      ))}
    </div>
  );
}

// ── Pre-flight checks (Step 1) ────────────────────────────────────────────
// Every row is derived from data the wizard already has in hand (the sheet
// identification response and its entity/join specs) — no connectivity pings
// or timings are simulated, since nothing in this backend measures those.
function PreflightRow({ status, name, detail }) {
  const icon =
    status === "pass" ? (
      <Check size={15} className="ct-preflight-row__icon is-pass" aria-hidden />
    ) : status === "warn" ? (
      <AlertTriangle size={15} className="ct-preflight-row__icon is-warn" aria-hidden />
    ) : (
      <Circle size={10} className="ct-preflight-row__icon is-pending" aria-hidden />
    );
  return (
    <div className="ct-preflight-row">
      <span className="ct-preflight-row__mk">{icon}</span>
      <span className="ct-preflight-row__name">{name}</span>
      <span className="ct-preflight-row__detail">{detail}</span>
    </div>
  );
}

function buildPreflightRows({ identification, sheetError, sourceSpec, targetSpec, canAuto, canContinueManual }) {
  if (!identification) {
    return [
      {
        status: "pending",
        name: "Mapping sheet parsed",
        detail: "Upload a mapping sheet to begin.",
      },
    ];
  }

  const rows = [];

  rows.push({
    status: sheetError ? "fail" : "pass",
    name: "Mapping sheet parsed",
    detail: sheetError
      ? sheetError
      : `${identification.parsed?.headers?.length ?? 0} columns · ${identification.parsed?.rows?.length ?? 0} rows`,
  });

  rows.push({
    status: identification.source?.kind ? "pass" : "warn",
    name: "Source system identified",
    detail: identification.source?.kind
      ? `${identification.source.label}${identification.source.confidence ? ` · ${identification.source.confidence} confidence` : ""}`
      : "Not identified — select the source connector manually on Step 2.",
  });

  rows.push({
    status: identification.target?.kind ? "pass" : "warn",
    name: "Target system identified",
    detail: identification.target?.kind
      ? `${identification.target.label}${identification.target.confidence ? ` · ${identification.target.confidence} confidence` : ""}`
      : "Not identified — select the target connector manually on Step 3.",
  });

  const unresolvedCount = (sourceSpec?.unresolved?.length ?? 0) + (targetSpec?.unresolved?.length ?? 0);
  const ambiguousCount = (sourceSpec?.ambiguous?.length ?? 0) + (targetSpec?.ambiguous?.length ?? 0);
  rows.push({
    status: unresolvedCount || ambiguousCount ? "warn" : "pass",
    name: "Entities resolve",
    detail:
      unresolvedCount || ambiguousCount
        ? `${unresolvedCount} unresolved, ${ambiguousCount} ambiguous — resolve in Additional Instructions.`
        : "All named entities exist on their connector.",
  });

  rows.push({
    status: canAuto ? "pass" : canContinueManual ? "warn" : "pending",
    name: "Ready to run",
    detail: canAuto
      ? "Both sides identified — Automatic is available."
      : canContinueManual
        ? "Continue manually through Source, Target and Mapping."
        : "Select a dataset type to continue.",
  });

  return rows;
}

function ComparisonTypeStep() {
  const { state, dispatch } = useWizard();
  const selectedId = state.comparisonType?.id ?? "";
  const identification = state.sheetIdentification;

  const sheetInputRef = useRef(null);
  const [sheetLoading, setSheetLoading] = useState(false);
  const [sheetError, setSheetError] = useState(null);

  const [instrBusy, setInstrBusy] = useState(false);
  const [instrError, setInstrError] = useState(null);

  const handleChange = (event) => {
    const id = event.target.value;
    if (!id) {
      dispatch({ type: WizardActions.SET_COMPARISON_TYPE, comparisonType: null });
      return;
    }
    const option = COMPARISON_TYPES.find((c) => c.id === id);
    dispatch({
      type: WizardActions.SET_COMPARISON_TYPE,
      comparisonType: { id: option.id, label: option.label },
    });
  };

  // Upload → parse (deterministic) → identify (LLM, allow-listed). Both go
  // through the existing endpoints; identification degrades gracefully, so a
  // failure here never blocks the wizard — the user just selects connectors
  // manually on Steps 2/3. The Step 4 mapping-sheet upload is untouched.
  const handleSheetFile = async (file) => {
    if (!file) return;
    setSheetError(null);
    setSheetLoading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const parseRes = await api.post("/api/recon/mapping-sheet/parse", formData);
      // include_entities: the same identification call also returns which
      // entities to fetch per side and any implied join, gated against each
      // side's live entity list. Pre-populates the Join Builder canvas.
      const idRes = await api.post("/api/recon/mapping-sheet/identify", {
        mapping_sheet: parseRes.data,
        include_entities: true,
      });
      dispatch({
        type: WizardActions.SET_SHEET_IDENTIFICATION,
        identification: {
          ...idRes.data,
          sheet: { name: file.name, size: file.size },
          parsed: parseRes.data,
        },
      });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setSheetError(
        typeof detail === "string" ? detail : "Could not read/identify the mapping sheet."
      );
    } finally {
      setSheetLoading(false);
      if (sheetInputRef.current) sheetInputRef.current.value = "";
    }
  };

  const clearSheet = () => {
    dispatch({ type: WizardActions.CLEAR_SHEET_IDENTIFICATION });
    dispatch({ type: WizardActions.CLEAR_ENTITY_JOIN, role: "source" });
    dispatch({ type: WizardActions.CLEAR_ENTITY_JOIN, role: "target" });
    setSheetError(null);
    if (sheetInputRef.current) sheetInputRef.current.value = "";
  };

  const canContinueManual = useMemo(() => Boolean(state.comparisonType), [state.comparisonType]);

  const hasIdentification = Boolean(identification && !identification.degraded);

  // Auto mode requires the mapping sheet to have actually resolved both
  // sides to a configured connector + entity — otherwise the pipeline would
  // hard-stop at step 1 every time. Manual's gate stays untouched (Excel
  // upload can still happen later, on the Source/Target steps).
  const canAuto =
    canContinueManual &&
    hasIdentification &&
    Boolean(identification?.source?.kind) &&
    Boolean(identification?.target?.kind);

  // Each side's entity/join input is resolved against ITS OWN connector kind:
  // the one the sheet identified for that side, else that role's sole live
  // connector. Resolving the two sides separately is what keeps a source
  // instruction from ever resolving to a target entity.
  const sourceKind = liveKindForRole("source", identification?.source);
  const targetKind = liveKindForRole("target", identification?.target);

  // ── Additional Instructions: ONE box, fired at BOTH sides ───────────────
  // The same text is sent to /entity-join/parse once scoped to sourceKind and
  // once to targetKind. Each call is independently existence-gated against
  // that connector's own live entities, so a sentence naming an S/4 entity
  // and an IBP planning area resolves correctly on both sides without this
  // box ever needing to know which words belong to which side.
  const instructionsText = state.entityJoin?.source?.text ?? "";

  const setInstructions = (text) => {
    dispatch({ type: WizardActions.SET_ENTITY_JOIN_TEXT, role: "source", text });
    dispatch({ type: WizardActions.SET_ENTITY_JOIN_TEXT, role: "target", text });
  };

  const resolveInstructions = async () => {
    if (!instructionsText.trim()) return;
    // Planning area is never set separately here — the same free text carries
    // it (e.g. "use IBP planning area ZOBP2508"), and each call below is
    // gated/extracted by the backend exactly like every other instruction.
    const targets = [
      { role: "source", kind: sourceKind },
      { role: "target", kind: targetKind },
    ].filter((t) => t.kind);
    if (targets.length === 0) return;

    setInstrBusy(true);
    setInstrError(null);
    try {
      await Promise.all(
        targets.map(async ({ role, kind }) => {
          const res = await api.post("/api/recon/entity-join/parse", {
            kind,
            text: instructionsText,
          });
          dispatch({ type: WizardActions.SET_ENTITY_JOIN_PARSED, role, parsed: res.data ?? null });
        })
      );
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setInstrError(typeof detail === "string" ? detail : "Could not read that instruction.");
    } finally {
      setInstrBusy(false);
    }
  };

  const clearInstructions = () => {
    dispatch({ type: WizardActions.CLEAR_ENTITY_JOIN, role: "source" });
    dispatch({ type: WizardActions.CLEAR_ENTITY_JOIN, role: "target" });
    setInstrError(null);
  };

  // ── Auto/Manual: replaces the shell's generic Continue button ───────────
  const navigate = useNavigate();
  const wizardSteps = useMemo(() => getVisibleSteps(), []);

  const goToStep = (target) => {
    dispatch({ type: WizardActions.GO_TO_STEP, step: target.key });
    navigate(`/reconciliation/${target.path}`);
  };

  const handleManualContinue = () => {
    dispatch({ type: WizardActions.COMPLETE_STEP, step: "comparisonType" });
    const next = wizardSteps[wizardSteps.findIndex((s) => s.key === "comparisonType") + 1];
    if (next) goToStep(next);
  };

  const [autoRunning, setAutoRunning] = useState(false);
  const [autoElapsedMs, setAutoElapsedMs] = useState(0);
  const [autoCurrentStep, setAutoCurrentStep] = useState(null);
  // Live "batch N of M (2023-2024)" progress within the pair_values step —
  // year-range batches of the AI value-pairing call (see
  // value_pairing.pipeline.pair_values' on_batch hook). null outside that step.
  const [autoBatchProgress, setAutoBatchProgress] = useState(null);
  const [autoError, setAutoError] = useState(null);
  const [autoFailedStep, setAutoFailedStep] = useState(null);

  const autoStartRef = useRef(null);
  const tickIntervalRef = useRef(null);
  const pollIntervalRef = useRef(null);
  const appliedRef = useRef({ source: false, target: false, mapping: false });

  useEffect(() => {
    // Stop any in-flight timers if the user navigates away mid-run.
    return () => {
      if (tickIntervalRef.current) clearInterval(tickIntervalRef.current);
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  const sideDataset = (role, side) => ({
    datasetId: `${role}-${side.kind}-auto-${side.snapshot_id ?? "pending"}`,
    filename: `${role === "source" ? identification?.source?.label : identification?.target?.label} — ${side.primary_entity}`,
    kind: side.kind,
    columns: side.columns ?? [],
    preview: [],
    rowCount: side.row_count ?? 0,
    colCount: (side.columns ?? []).length,
    rows: null,
    file: null,
    sheet: null,
    sheets: [],
    fetchedAt: new Date().toISOString(),
    mdtFields: [],
  });

  // Applies whatever the run has produced SO FAR to wizard state — called on
  // every poll tick, not just on completion, so a mid-run hard-stop still
  // leaves already-succeeded steps usable if the user switches to Manual.
  const applyPartialResult = (result) => {
    if (!result) return;
    if (result.source?.snapshot_id && !appliedRef.current.source) {
      appliedRef.current.source = true;
      dispatch({ type: WizardActions.SET_DATASET, role: "source", dataset: sideDataset("source", result.source) });
      dispatch({ type: WizardActions.COMPLETE_STEP, step: "source" });
    }
    if (result.target?.snapshot_id && !appliedRef.current.target) {
      appliedRef.current.target = true;
      dispatch({ type: WizardActions.SET_DATASET, role: "target", dataset: sideDataset("target", result.target) });
      dispatch({ type: WizardActions.COMPLETE_STEP, step: "target" });
    }
    if ((result.product_mapping || result.location_mapping) && !appliedRef.current.mapping) {
      appliedRef.current.mapping = true;
      dispatch({
        type: WizardActions.SET_VALUE_MAPPINGS,
        valueMappings: { product: result.product_mapping ?? null, location: result.location_mapping ?? null },
      });
      dispatch({ type: WizardActions.SET_MAPPING_MODE, mappingMode: "deterministic" });
    }
  };

  const finishAutoRun = async (result) => {
    applyPartialResult(result);
    if (result?.contract_id) {
      try {
        const contractRes = await api.get(`/api/recon/contracts/${result.contract_id}/approved`);
        if (contractRes.data?.contract) {
          dispatch({ type: WizardActions.SET_DETERMINISTIC_CONTRACT, contract: contractRes.data.contract });
        }
      } catch {
        // Non-fatal — Results still renders from the reconciliation result alone.
      }
    }
    if (result?.result_summary) {
      dispatch({ type: WizardActions.SET_RECONCILIATION_RESULT, result: result.result_summary });
    }
    dispatch({ type: WizardActions.COMPLETE_STEP, step: "comparisonType" });
    dispatch({ type: WizardActions.COMPLETE_STEP, step: "transformationSpec" });
    dispatch({ type: WizardActions.COMPLETE_STEP, step: "reconciliation" });
    setAutoRunning(false);
    goToStep(getStepByKey("reconciliation"));
  };

  const pollAutoRun = async (graphRunId) => {
    try {
      const res = await api.get(`/api/recon/auto-run/${graphRunId}/status`);
      const run = res.data;
      setAutoCurrentStep(run.current_step);
      setAutoBatchProgress(run.batch_progress ?? null);
      applyPartialResult(run.result);
      if (run.status === "completed") {
        clearInterval(pollIntervalRef.current);
        clearInterval(tickIntervalRef.current);
        await finishAutoRun(run.result);
      } else if (run.status === "failed") {
        clearInterval(pollIntervalRef.current);
        clearInterval(tickIntervalRef.current);
        setAutoRunning(false);
        setAutoFailedStep(run.failed_step);
        setAutoError(run.error || "Auto mode failed.");
      }
    } catch {
      // A transient poll failure shouldn't abort the run — the next tick retries.
    }
  };

  const startAutoRun = async () => {
    setAutoError(null);
    setAutoFailedStep(null);
    setAutoCurrentStep(null);
    setAutoBatchProgress(null);
    setAutoElapsedMs(0);
    appliedRef.current = { source: false, target: false, mapping: false };
    setAutoRunning(true);

    autoStartRef.current = Date.now();
    tickIntervalRef.current = setInterval(() => {
      setAutoElapsedMs(Date.now() - autoStartRef.current);
    }, 250);

    try {
      const res = await api.post("/api/recon/auto-run/start", {
        mapping_sheet: identification.parsed,
        identification: { source: identification.source, target: identification.target },
        comparison_type: state.comparisonType?.id ?? null,
        actor: "auto",
      });
      const graphRunId = res.data.graph_run_id;
      pollIntervalRef.current = setInterval(() => pollAutoRun(graphRunId), 1000);
    } catch (err) {
      clearInterval(tickIntervalRef.current);
      setAutoRunning(false);
      const detail = err?.response?.data?.detail;
      setAutoError(typeof detail === "string" ? detail : "Could not start Auto mode.");
    }
  };

  // ── Run mode: segmented Manual/Automatic selector + a single Start action,
  // matching the Enterprise UI layout. Selecting a mode doesn't act by
  // itself — Start still calls the exact same handleManualContinue /
  // startAutoRun as before. ──────────────────────────────────────────────
  const [runModeChoice, setRunModeChoice] = useState("manual");
  // Falls back to Manual whenever Automatic isn't actually available, rather
  // than syncing it via an effect (there's nothing external to synchronize
  // with — it's a pure function of state already in hand).
  const runMode = runModeChoice === "auto" && !canAuto ? "manual" : runModeChoice;

  const sourceSpec = effectiveEntityJoin(state, "source");
  const targetSpec = effectiveEntityJoin(state, "target");
  const preflightRows = useMemo(
    () => buildPreflightRows({ identification, sheetError, sourceSpec, targetSpec, canAuto, canContinueManual }),
    [identification, sheetError, sourceSpec, targetSpec, canAuto, canContinueManual]
  );

  const fileMetaText = identification
    ? [
        identification.sheet?.size != null ? `${Math.round(identification.sheet.size / 1024)} KB` : null,
        identification.parsed?.rows ? `${identification.parsed.rows.length} rows` : null,
      ]
        .filter(Boolean)
        .join(" · ")
    : "";

  return (
    <StepShell stepKey="comparisonType" hideContinue>
      <div className="ct-grid">
        {/* ══ Left column: Mapping sheet + Pre-flight checks ══ */}
        <div className="ct-col">
          <section className="ct-card ct-card--tint-blue">
            <div className="ct-card__head">
              <h3 className="ct-card__title">Mapping sheet</h3>
              <span className="ct-card__spacer" />
              {hasIdentification && (
                <Badge variant="success" dot>
                  Detected
                </Badge>
              )}
            </div>
            <div className="ct-card__body">
              <input
                ref={sheetInputRef}
                type="file"
                accept={SHEET_ACCEPT}
                style={{ display: "none" }}
                onChange={(e) => handleSheetFile(e.target.files?.[0] ?? null)}
              />

              {!identification ? (
                <>
                  <p className="wizard-field__help" style={{ marginTop: 0 }}>
                    Upload a mapping workbook to auto-detect the source/target connectors, fields,
                    entities and join.
                  </p>
                  <UploadDropzone
                    onPick={() => sheetInputRef.current?.click()}
                    onDropFile={handleSheetFile}
                    loading={sheetLoading}
                  />
                </>
              ) : (
                <div className="ct-mapping-body">
                  <div className="ct-file-row">
                    <FileSpreadsheet className="ct-file-row__icon" aria-hidden />
                    <span className="ct-file-row__name" title={identification.sheet?.name}>
                      {identification.sheet?.name ?? "mapping sheet"}
                    </span>
                    {fileMetaText && <span className="ct-file-row__meta mono">{fileMetaText}</span>}
                    <span className="ct-card__spacer" />
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => sheetInputRef.current?.click()}
                      disabled={sheetLoading}
                    >
                      {sheetLoading ? (
                        <Loader2 size={12} className="animate-spin" aria-hidden />
                      ) : (
                        "Replace"
                      )}
                    </Button>
                    <Button variant="outline" size="sm" onClick={clearSheet} disabled={sheetLoading}>
                      <X size={12} aria-hidden />
                      Remove
                    </Button>
                  </div>

                  {hasIdentification && (
                    <table className="ct-table">
                      <thead>
                        <tr>
                          <th>Side</th>
                          <th>System</th>
                          <th>Confidence</th>
                          <th>Entities</th>
                          <th>Join</th>
                          <th>Fields</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[
                          { title: "Source", side: identification.source, spec: sourceSpec },
                          { title: "Target", side: identification.target, spec: targetSpec },
                        ].map(({ title, side, spec }) => {
                          const join = spec ? joinSummary(spec) : null;
                          return (
                            <tr key={title}>
                              <td>{title}</td>
                              <td>{side?.kind ? side.label : "Not identified"}</td>
                              <td>
                                {side?.kind ? (
                                  <Badge variant="success" dot>
                                    {side.confidence ?? "—"}
                                  </Badge>
                                ) : (
                                  <Badge variant="warning">Unknown</Badge>
                                )}
                              </td>
                              <td className="mono">
                                {spec?.entities?.length ? spec.entities.join(", ") : "—"}
                              </td>
                              <td>
                                {!spec || spec.entities.length < 2
                                  ? "Single entity"
                                  : `${join.typeLabel} join on ${join.keysLabel}`}
                              </td>
                              <td style={{ textAlign: "right" }}>{side?.fields?.length ?? 0}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  )}

                  {identification.degraded && identification.degraded_reason && (
                    <Alert variant="warning">{identification.degraded_reason}</Alert>
                  )}
                </div>
              )}

              {sheetError && <Alert variant="error">{sheetError}</Alert>}
            </div>
          </section>

          {/* Detection details: its own always-visible card — no click needed
              to see confidence/evidence/join reasoning. */}
          {hasIdentification && (
            <section className="ct-card">
              <div className="ct-card__head">
                <h3 className="ct-card__title">Detection details</h3>
              </div>
              <div className="ct-card__body">
                <DetectionDetails state={state} identification={identification} />
              </div>
            </section>
          )}

          <section className="ct-card ct-card--tint-yellow">
            <div className="ct-card__head">
              <h3 className="ct-card__title">Pre-flight checks</h3>
            </div>
            <div className="ct-card__body ct-card__body--flush">
              {preflightRows.map((row) => (
                <PreflightRow key={row.name} {...row} />
              ))}
            </div>
          </section>
        </div>

        {/* ══ Right column: Run configuration ══ */}
        <div className="ct-col">
          <section className="ct-card">
            <div className="ct-card__head">
              <h3 className="ct-card__title">Run configuration</h3>
            </div>
            <div className="ct-card__body ct-card__body--stack">
              <div className="wizard-field" style={{ maxWidth: "none" }}>
                <label className="wizard-field__label" htmlFor="comparison-type-select">
                  Dataset Type
                </label>
                <Select
                  id="comparison-type-select"
                  value={selectedId}
                  onChange={handleChange}
                  options={[
                    { value: "", label: "Select a dataset type…" },
                    ...COMPARISON_TYPES.map((option) => ({ value: option.id, label: option.label })),
                  ]}
                />
                {state.comparisonType && (
                  <div className="wizard-dataset-summary">
                    <Badge variant="success">Selected</Badge>
                    <span>{state.comparisonType.label}</span>
                  </div>
                )}
              </div>

              {/* ── Run mode: segmented Manual/Automatic + single Start action ── */}
              <div className="ct-runmode">
                <p className="wizard-field__label">Run mode</p>

                {autoRunning ? (
                  <div className="wizard-auto-progress">
                    <Loader2 size={16} className="animate-spin" aria-hidden />
                    <span className="wizard-auto-progress__step">
                      {AUTO_STEP_LABELS[autoCurrentStep] ?? "Starting…"}
                      {autoCurrentStep === "pair_values" && autoBatchProgress && (
                        <> — batch {autoBatchProgress.batch_index + 1} of{" "}
                        {autoBatchProgress.batch_count} ({autoBatchProgress.batch_label})</>
                      )}
                    </span>
                    <span className="wizard-auto-progress__timer">{formatElapsed(autoElapsedMs)}</span>
                  </div>
                ) : (
                  <>
                    <div className="ct-runmode-toggle">
                      <button
                        type="button"
                        className={runMode === "manual" ? "is-active" : ""}
                        onClick={() => setRunModeChoice("manual")}
                      >
                        Manual
                      </button>
                      <button
                        type="button"
                        className={runMode === "auto" ? "is-active" : ""}
                        onClick={() => canAuto && setRunModeChoice("auto")}
                        disabled={!canAuto}
                      >
                        Automatic
                      </button>
                    </div>
                    <p className="wizard-field__help">
                      {runMode === "auto"
                        ? "Run all steps automatically and land on Results."
                        : "Step through source, target and mapping with approval at each step."}
                    </p>
                    {runMode === "auto" && !canAuto && (
                      <p className="wizard-field__help">
                        Requires the mapping sheet to resolve both source and target systems.
                      </p>
                    )}
                    <Button
                      variant="primary"
                      onClick={runMode === "auto" ? startAutoRun : handleManualContinue}
                      disabled={runMode === "auto" ? !canAuto : !canContinueManual}
                    >
                      {runMode === "auto" ? "Start automatic run" : "Start manual run"}
                    </Button>
                  </>
                )}

                {!autoRunning && autoElapsedMs > 0 && !autoError && (
                  <p className="wizard-field__help">Last Auto run took {formatElapsed(autoElapsedMs)}.</p>
                )}

                {autoError && (
                  <Alert variant="error">
                    {autoFailedStep ? `Auto mode failed at "${AUTO_STEP_LABELS[autoFailedStep] ?? autoFailedStep}": ` : ""}
                    {autoError}
                    <div className="wizard-instructions__actions" style={{ marginTop: 8 }}>
                      <Button variant="secondary" size="sm" onClick={startAutoRun}>
                        Retry Auto
                      </Button>
                      <button type="button" className="wizard-link" onClick={handleManualContinue}>
                        Switch to Manual
                      </button>
                    </div>
                  </Alert>
                )}
              </div>
            </div>
          </section>

          {/* Additional instructions: its own always-visible card, not hidden
              behind a click — optional, but never out of sight. */}
          <section className="ct-card">
            <div className="ct-card__head">
              <h3 className="ct-card__title">Additional instructions</h3>
              <span className="ct-hint-badge--optional">Optional</span>
              <span className="ct-card__spacer" />
              {instructionsText && <Badge variant="teal">Set</Badge>}
            </div>
            <div className="ct-card__body">
              <div className="wizard-instructions">
                <p className="wizard-field__help" style={{ marginTop: 0 }}>
                  Describe S/4 entities, the IBP planning area, joins, or mapping overrides in plain
                  language.
                </p>
                <textarea
                  id="additional-instructions"
                  aria-label="Additional Instructions"
                  className="wizard-instructions__textarea"
                  rows={2}
                  placeholder='e.g. "Join SalesOrder and ScheduleLine with a left join on SalesOrder; use IBP planning area ZOBP2508"'
                  value={instructionsText}
                  onChange={(e) => setInstructions(e.target.value)}
                />
                <div className="wizard-instructions__actions">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={resolveInstructions}
                    loading={instrBusy}
                    disabled={instrBusy || !instructionsText.trim()}
                  >
                    {instrBusy ? "Applying…" : "Apply"}
                  </Button>
                  {instructionsText && (
                    <button type="button" className="wizard-link" onClick={clearInstructions}>
                      Clear
                    </button>
                  )}
                </div>
                {instrError && <Alert variant="error">{instrError}</Alert>}
              </div>
            </div>
          </section>
        </div>
      </div>
    </StepShell>
  );
}

export default ComparisonTypeStep;
