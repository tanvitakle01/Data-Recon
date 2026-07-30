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
import { Badge, Select, Button, Alert, CollapsibleSection } from "@bristlecone/canopy";
import { Upload, FileSpreadsheet, X, Loader2 } from "lucide-react";

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

// ── File chip (filled state) ──────────────────────────────────────────────
// Replaces the upload button once a file exists: name, status, Remove — and
// nothing else. Everything else on this step reacts to this file's result.
function FileChip({ name, loading, detected, onRemove }) {
  const statusClass = loading ? "is-busy" : detected ? "is-detected" : "is-plain";
  return (
    <div className="wizard-file-chip">
      
      <FileSpreadsheet className="wizard-file-chip__icon" aria-hidden />
      <span className="wizard-file-chip__name" title={name}>
        {name}
      </span>
      <span className={`wizard-file-chip__status ${statusClass}`}>
        {loading && <Loader2 size={12} className="animate-spin" aria-hidden />}
        {loading ? "Analyzing…" : detected ? "Auto-detected" : "Uploaded"}
      </span>
      <button type="button" className="wizard-file-chip__remove" onClick={onRemove}>
        <X size={14} aria-hidden />
        Remove
      </button>
    </div>
  );
}

// ── Auto-detected summary ─────────────────────────────────────────────────
// The default, always-visible readout — five lines, no prose. Everything
// more detailed lives behind "Detection Details" below.
function AutoDetectedSummary({ state, identification }) {
  const source = identification.source;
  const target = identification.target;
  const sourceSpec = effectiveEntityJoin(state, "source");
  const targetSpec = effectiveEntityJoin(state, "target");

  const planningArea = sourceSpec?.planningArea || targetSpec?.planningArea || null;
  const planningNeeded =
    !planningArea && Boolean(sourceSpec?.ambiguous?.length || targetSpec?.ambiguous?.length);

  const sourceEntityLabel = sourceSpec?.entities?.length
    ? sourceSpec.entities.length > 1
      ? `${sourceSpec.entities[0]} + ${sourceSpec.entities.length - 1} more`
      : sourceSpec.entities[0]
    : null;

  const fieldCount = (source?.fields?.length ?? 0) + (target?.fields?.length ?? 0);

  return (
    <div className="wizard-summary">
      <div className="wizard-summary__row">
        <span className="wizard-summary__label">Source connector</span>
        {source?.kind ? (
          <Badge variant="success" dot>
            {source.label}
          </Badge>
        ) : (
          <Badge variant="warning">Not identified</Badge>
        )}
      </div>
      <div className="wizard-summary__row">
        <span className="wizard-summary__label">Target connector</span>
        {target?.kind ? (
          <Badge variant="success" dot>
            {target.label}
          </Badge>
        ) : (
          <Badge variant="warning">Not identified</Badge>
        )}
      </div>
      {(planningArea || planningNeeded) && (
        <div className="wizard-summary__row">
          <span className="wizard-summary__label">Planning area</span>
          {planningArea ? (
            <span className="wizard-summary__value">{planningArea}</span>
          ) : (
            <span className="wizard-summary__warn">Needed — name it in Additional Instructions</span>
          )}
        </div>
      )}
      {sourceEntityLabel && (
        <div className="wizard-summary__row">
          <span className="wizard-summary__label">Source entity</span>
          <span className="wizard-summary__value">{sourceEntityLabel}</span>
        </div>
      )}
      <div className="wizard-summary__row">
        <span className="wizard-summary__label">Fields identified</span>
        <span className="wizard-summary__value">{fieldCount}</span>
      </div>
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

  return (
    <StepShell stepKey="comparisonType" hideContinue>
      {/* ── Mapping Sheet Upload: the primary action on this step ── */}
      <div className="wizard-field wizard-mapping-upload">
        <label className="wizard-field__label">Mapping Sheet</label>
        <p className="wizard-field__help">
          Upload a mapping workbook to auto-detect the source/target connectors, fields, entities
          and join.
        </p>

        <input
          ref={sheetInputRef}
          type="file"
          accept={SHEET_ACCEPT}
          style={{ display: "none" }}
          onChange={(e) => handleSheetFile(e.target.files?.[0] ?? null)}
        />

        {!identification ? (
          <UploadDropzone
            onPick={() => sheetInputRef.current?.click()}
            onDropFile={handleSheetFile}
            loading={sheetLoading}
          />
        ) : (
          <div className="wizard-mapping-upload__body">
            <FileChip
              name={identification.sheet?.name ?? "mapping sheet"}
              loading={sheetLoading}
              detected={hasIdentification}
              onRemove={clearSheet}
            />

            {hasIdentification && <AutoDetectedSummary state={state} identification={identification} />}

            {identification.degraded && identification.degraded_reason && (
              <Alert variant="warning" style={{ marginTop: 8 }}>
                {identification.degraded_reason}
              </Alert>
            )}

            {hasIdentification && (
              <CollapsibleSection title="Detection Details" className="wizard-collapsible">
                <DetectionDetails state={state} identification={identification} />
              </CollapsibleSection>
            )}

            {/* ── Additional Instructions: the single free-text fallback, collapsed
                like the other advanced sections until the user opts in ── */}
            <CollapsibleSection
              title="Additional Instructions"
              subtitle="Optional"
              className="wizard-collapsible"
              badge={instructionsText ? <Badge variant="teal">Set</Badge> : null}
            >
              <div className="wizard-instructions">
                <p className="wizard-field__help">
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
                {instrError && (
                  <Alert variant="error" style={{ marginTop: 8 }}>
                    {instrError}
                  </Alert>
                )}
              </div>
            </CollapsibleSection>
          </div>
        )}

        {sheetError && (
          <Alert variant="error" style={{ marginTop: 8 }}>
            {sheetError}
          </Alert>
        )}
      </div>

      {/* ── Dataset Type ── */}
      <div className="wizard-field">
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
      </div>

      {state.comparisonType && (
        <div className="wizard-dataset-summary">
          <Badge variant="success">Selected</Badge>
          <span>{state.comparisonType.label}</span>
        </div>
      )}

      {/* ── Auto/Manual: replaces the generic Continue button ── */}
      <div className="wizard-field wizard-run-mode">
        <label className="wizard-field__label">How should this run proceed?</label>

        {autoRunning ? (
          <div className="wizard-auto-progress">
            <Loader2 size={16} className="animate-spin" aria-hidden />
            <span className="wizard-auto-progress__step">
              {AUTO_STEP_LABELS[autoCurrentStep] ?? "Starting…"}
            </span>
            <span className="wizard-auto-progress__timer">{formatElapsed(autoElapsedMs)}</span>
          </div>
        ) : (
          <div className="wizard-source-choice">
            <button
              type="button"
              className="wizard-choice-card"
              onClick={handleManualContinue}
              disabled={!canContinueManual}
            >
              <span className="wizard-choice-card__label">Manual</span>
              <span className="wizard-choice-card__meta">
                Step through source, target and mapping with approval at each step
              </span>
            </button>
            <button
              type="button"
              className="wizard-choice-card"
              onClick={startAutoRun}
              disabled={!canAuto}
            >
              <span className="wizard-choice-card__label">Auto</span>
              <span className="wizard-choice-card__meta">
                {canAuto
                  ? "Run all steps automatically and land on Results"
                  : "Requires the mapping sheet to resolve both source and target systems"}
              </span>
            </button>
          </div>
        )}

        {!autoRunning && autoElapsedMs > 0 && !autoError && (
          <p className="wizard-field__help">Last Auto run took {formatElapsed(autoElapsedMs)}.</p>
        )}

        {autoError && (
          <Alert variant="error" style={{ marginTop: 8 }}>
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
    </StepShell>
  );
}

export default ComparisonTypeStep;
