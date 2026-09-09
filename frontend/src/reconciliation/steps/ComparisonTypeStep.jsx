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
import {
  Upload,
  FileSpreadsheet,
  X,
  Loader2,
  Check,
  AlertTriangle,
  Circle,
  Sparkles,
} from "lucide-react";
import ResolverPanel from "../components/ResolverPanel";

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

// Mirrors backend/recon_engine/auto_pipeline/state.py's STEP_NAMES exactly —
// keep the two in sync if either changes.
const AUTO_STEP_LABELS = {
  select_source: "Selecting source system…",
  select_target: "Selecting target system…",
  resolve_schema: "Resolving schema & candidate business keys (AI)…",
  compile_contract: "Compiling reconciliation contract…",
  plan_date_batches: "Planning batches…",
  run_batches: "Running batches…",
  finalize: "Finalizing results…",
};

// Mirrors backend/recon_engine/auto_pipeline/nodes.py's `_report_batch_stage`
// stage names exactly — keep the two in sync if either changes.
const AUTO_BATCH_STAGE_LABELS = {
  fetching_source: "fetching source data",
  fetching_target: "fetching target data",
  pairing_values: "pairing values",
  reconciling: "reconciling",
  completed: "batch reconciled",
};

// The Dataset Type list is no longer static: it is the interface list read
// from the uploaded workbook's "Interfaces" index sheet (see
// backend/recon_engine/interface_index.py). Until a workbook is parsed there
// are no dataset types to offer at all.

const SHEET_ACCEPT = ".xlsx,.xls,.csv";

// Suffix shown on an interface that can't be run because its worksheet
// couldn't be resolved. It stays LISTED (greyed out) rather than silently
// dropped, so an incomplete workbook is visible instead of mysterious.
function brokenReason(iface) {
  if (iface.match === "ambiguous") {
    return `matches ${iface.candidates?.length ?? 2} sheets`;
  }
  return "sheet missing";
}

// ── Upload (empty state) ──────────────────────────────────────────────────
// A single compact dropzone row — icon, copy, button — so the card carries
// the workbook's interface list rather than being dominated by the picker.
// Drag/drop still works across the whole row; the hint says so in the caption.
function UploadDropzone({ onPick, onDropFile, loading }) {
  const [dragOver, setDragOver] = useState(false);
  return (
    <div
      className={`wizard-upload-row ${dragOver ? "is-dragover" : ""}`}
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
      <Upload className="wizard-upload-row__icon" aria-hidden />
      <div className="wizard-upload-row__text">
        <p className="wizard-upload-row__title">Upload your mapping sheet</p>
        <p className="wizard-upload-row__hint">
          Drag &amp; drop, or choose a file (.xlsx, .xls, .csv)
        </p>
      </div>
      <Button variant="primary" size="sm" onClick={onPick} loading={loading} disabled={loading}>
        {loading ? "Reading…" : "Upload"}
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

function buildPreflightRows({
  interfaceIndex,
  identification,
  sheetError,
  selectedInterface,
  sliceLoading,
  sourceSpec,
  targetSpec,
  canAuto,
  canContinueManual,
}) {
  const rows = [];

  // A one-sheet upload is the supported "I exported just this interface"
  // shape, not a workbook whose index went missing — so it reports as a pass
  // with nothing to choose, rather than as a degraded fallback.
  const singleSheet = Boolean(interfaceIndex?.single_sheet);

  // 1. The workbook read: reports the INTERFACE COUNT, which is what the
  //    parse now actually produces — the field tables are read later, one
  //    interface at a time.
  if (!interfaceIndex) {
    rows.push({
      status: sheetError ? "warn" : "pending",
      name: "Mapping sheet parsed",
      detail: sheetError ?? "Upload a mapping sheet to begin.",
    });
  } else {
    const all = interfaceIndex.interfaces ?? [];
    const broken = all.filter((i) => i.status === "broken");
    const count = `${all.length} interface${all.length === 1 ? "" : "s"} found`;
    rows.push({
      status: singleSheet ? "pass" : !interfaceIndex.indexed || broken.length > 0 ? "warn" : "pass",
      name: "Mapping sheet parsed",
      detail: singleSheet
        ? "Single sheet — no interface index needed."
        : !interfaceIndex.indexed
          ? `${count} from the workbook's sheet names — no interface index.`
          : count +
            (broken.length > 0
              ? ` · ${broken.length} could not be matched to a worksheet`
              : ""),
    });
  }

  // 2. Which single worksheet is being handed to interpretation. For an
  //    indexed workbook the rest is discarded, so it's worth saying which one
  //    won; for a one-sheet upload there was never anything else.
  rows.push({
    status: selectedInterface?.sheet ? "pass" : "pending",
    name: singleSheet ? "Dataset sheet" : "Interface selected",
    detail: selectedInterface?.sheet
      ? singleSheet
        ? `The uploaded "${selectedInterface.sheet}" sheet is the dataset.`
        : `Only the "${selectedInterface.sheet}" sheet is interpreted.`
      : interfaceIndex
        ? "Select a dataset type to slice its sheet."
        : "Waiting on a mapping sheet.",
  });

  if (!identification) {
    const detail = sliceLoading
      ? "Reading the selected interface's sheet…"
      : "Runs once a dataset type is selected.";
    rows.push({ status: "pending", name: "Source system identified", detail });
    rows.push({ status: "pending", name: "Target system identified", detail });
    rows.push({ status: "pending", name: "Entities resolve", detail });
    rows.push({
      status: "pending",
      name: "Ready to run",
      detail: canContinueManual
        ? "Continue manually through Source, Target and Mapping."
        : "Select a dataset type to continue.",
    });
    return rows;
  }

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
  const interfaceIndex = state.interfaceIndex;

  const interfaces = interfaceIndex?.interfaces ?? [];
  const selectedInterface = interfaces.find((i) => i.id === selectedId) ?? null;
  // A workbook whose index lists exactly one interface (or a single-sheet
  // upload) has nothing to choose — the dropdown is skipped and the interface
  // is auto-selected on upload.
  const singleInterface = interfaces.length === 1;
  // Specifically the one-sheet upload: the user sent a single interface's
  // sheet instead of the whole project workbook, so that sheet IS the dataset
  // and there is no "rest of the workbook" being discarded.
  const singleSheet = Boolean(interfaceIndex?.single_sheet);

  const sheetInputRef = useRef(null);
  const [sheetLoading, setSheetLoading] = useState(false);
  const [sheetError, setSheetError] = useState(null);
  // The chosen interface's own sheet being read + identified. Separate from
  // sheetLoading (the workbook index read) because they are separate phases:
  // the index read only ever yields the interface list.
  const [sliceLoading, setSliceLoading] = useState(false);

  const [instrBusy, setInstrBusy] = useState(false);
  const [instrError, setInstrError] = useState(null);

  // Slice ONE interface out of the workbook and interpret only that slice:
  // parse (deterministic, scoped to that worksheet) → identify (LLM,
  // allow-listed). The interpretation step itself is unchanged — only its
  // input scope is, from "the whole workbook" to "this interface's sheet".
  // Identification degrades gracefully, so a failure here never blocks the
  // wizard: the user just selects connectors manually on Steps 2/3.
  const selectInterface = async (iface, index = interfaceIndex) => {
    dispatch({ type: WizardActions.CLEAR_SHEET_IDENTIFICATION });
    if (!iface) {
      dispatch({ type: WizardActions.SET_COMPARISON_TYPE, comparisonType: null });
      return;
    }
    dispatch({
      type: WizardActions.SET_COMPARISON_TYPE,
      comparisonType: { id: iface.id, label: iface.record },
    });

    const file = index?.file;
    // A broken interface has no worksheet to slice — it is selectable-proof in
    // the dropdown, so this only guards a workbook re-read losing the File.
    if (!file || !iface.sheet) return;

    setSheetError(null);
    setSliceLoading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("sheet_name", iface.sheet);
      const parseRes = await api.post("/api/recon/mapping-sheet/parse", formData);
      // Also feeds Step 4 (Mapping): the Recipe Editor's "draft from
      // description" context, and the sequential AI mapping-resolution chain
      // (TransformationSpecStep) both read `transformationSpec.parsedMappingSheet`.
      // Dispatched before identify (below) so it's available even if
      // identification itself fails/degrades.
      dispatch({
        type: WizardActions.SET_PARSED_MAPPING_SHEET,
        parsedMappingSheet: parseRes.data,
      });
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
          // Which interface this identification came from — the rest of the
          // workbook played no part in it.
          interface: { id: iface.id, record: iface.record, sheet: iface.sheet },
          parsed: parseRes.data,
        },
      });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setSheetError(
        typeof detail === "string"
          ? detail
          : `Could not read/identify the "${iface.record}" interface.`
      );
    } finally {
      setSliceLoading(false);
    }
  };

  const handleChange = (event) => {
    const id = event.target.value;
    selectInterface(interfaces.find((i) => i.id === id) ?? null);
  };

  // Upload reads the workbook's INTERFACE INDEX only — no field table is read
  // and nothing is interpreted yet. The interface list it returns becomes the
  // Dataset Type options; the chosen one's sheet is sliced in selectInterface.
  const handleSheetFile = async (file) => {
    if (!file) return;
    setSheetError(null);
    setSheetLoading(true);
    // A different workbook invalidates the previous interface list, the
    // dataset type chosen from it, and anything identified from the old slice.
    dispatch({ type: WizardActions.SET_COMPARISON_TYPE, comparisonType: null });
    dispatch({ type: WizardActions.CLEAR_SHEET_IDENTIFICATION });
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await api.post("/api/recon/mapping-sheet/interfaces", formData);
      // The File is retained so selecting a dataset type can issue the scoped
      // parse without asking for the workbook again.
      const index = { ...res.data, file };
      dispatch({ type: WizardActions.SET_INTERFACE_INDEX, interfaceIndex: index });
      // Records the workbook itself (name/size) on transformationSpec — Step
      // 4 (Results export, the Recipe Editor's AI context) reads this. Also
      // resets parsedMappingSheet, which selectInterface below repopulates
      // once the chosen interface's sheet is parsed.
      dispatch({
        type: WizardActions.SET_MAPPING_SHEET,
        mappingSheet: { name: file.name, size: file.size, file },
      });

      const list = res.data.interfaces ?? [];
      if (list.length === 1 && list[0].status === "ok") {
        await selectInterface(list[0], index);
      }
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setSheetError(
        typeof detail === "string" ? detail : "Could not read the mapping workbook."
      );
    } finally {
      setSheetLoading(false);
      if (sheetInputRef.current) sheetInputRef.current.value = "";
    }
  };

  const clearSheet = () => {
    dispatch({ type: WizardActions.CLEAR_INTERFACE_INDEX });
    dispatch({ type: WizardActions.SET_COMPARISON_TYPE, comparisonType: null });
    dispatch({ type: WizardActions.CLEAR_SHEET_IDENTIFICATION });
    dispatch({ type: WizardActions.SET_MAPPING_SHEET, mappingSheet: null });
    dispatch({ type: WizardActions.CLEAR_ENTITY_JOIN, role: "source" });
    dispatch({ type: WizardActions.CLEAR_ENTITY_JOIN, role: "target" });
    setSheetError(null);
    if (sheetInputRef.current) sheetInputRef.current.value = "";
  };

  // Both gates, not just the dataset type: the run needs a parsed workbook to
  // have produced the interface AND that interface to have been chosen.
  const canContinueManual = useMemo(
    () => Boolean(state.comparisonType) && Boolean(state.interfaceIndex),
    [state.comparisonType, state.interfaceIndex]
  );

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
  // Live "N/M batches done" + current-batch sub-stage while the run is inside
  // the run_batches step — one date-batch at a time (see auto_pipeline.nodes'
  // _do_run_batches/_report_batch_stage). null outside that step.
  const [autoBatchProgress, setAutoBatchProgress] = useState(null);
  const [autoError, setAutoError] = useState(null);
  const [autoSuspendable, setAutoSuspendable] = useState(false);
  const [autoSuspending, setAutoSuspending] = useState(false);
  const [autoSuspended, setAutoSuspended] = useState(false);
  const [autoFailedStep, setAutoFailedStep] = useState(null);

  // ── Error-resolver bot: opens when Auto pauses on a RECOVERABLE resolution
  // failure (entity/field/join-key not resolved) — never on an unrecoverable
  // one, which still lands in autoError/autoFailedStep above unchanged. ────
  const [autoInterrupt, setAutoInterrupt] = useState(null);
  const [resolverOpen, setResolverOpen] = useState(false);
  const [resolverBusy, setResolverBusy] = useState(false);
  const [resolverError, setResolverError] = useState(null);

  const autoStartRef = useRef(null);
  const tickIntervalRef = useRef(null);
  const pollIntervalRef = useRef(null);
  const graphRunIdRef = useRef(null);
  const lastInterruptKeyRef = useRef(null);
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
      setAutoSuspendable(Boolean(run.suspendable));
      applyPartialResult(run.result);

      if (run.status === "waiting_for_input" && run.interrupt) {
        // Re-open on a genuinely NEW question (including a re-ask after an
        // invalid answer) — but leave it alone if the user already
        // dismissed THIS same one and nothing has changed yet.
        const key = `${run.interrupt.message}|${run.interrupt.attempted}`;
        if (key !== lastInterruptKeyRef.current) {
          lastInterruptKeyRef.current = key;
          setResolverOpen(true);
          setResolverError(null);
        }
        setAutoInterrupt(run.interrupt);
        setResolverBusy(false);
        return;
      }

      setAutoInterrupt(null);

      if (run.status === "completed") {
        clearInterval(pollIntervalRef.current);
        clearInterval(tickIntervalRef.current);
        setResolverOpen(false);
        await finishAutoRun(run.result);
      } else if (run.status === "failed") {
        clearInterval(pollIntervalRef.current);
        clearInterval(tickIntervalRef.current);
        setAutoRunning(false);
        setResolverOpen(false);
        setAutoFailedStep(run.failed_step);
        setAutoError(run.error || "Auto mode failed.");
      } else if (run.status === "suspended") {
        clearInterval(pollIntervalRef.current);
        clearInterval(tickIntervalRef.current);
        setAutoRunning(false);
        setAutoSuspending(false);
        setResolverOpen(false);
        setAutoSuspended(true);
      }
    } catch {
      // A transient poll failure shouldn't abort the run — the next tick retries.
    }
  };

  // Offer-and-accept only — never automatic (see build notes). Suspend takes
  // effect at the next batch boundary; the existing poll loop keeps running
  // until the status flips to "suspended" above, so no extra polling logic
  // is needed here.
  const suspendAutoRun = async () => {
    const graphRunId = graphRunIdRef.current;
    if (!graphRunId) return;
    // A FAILED run converts to SUSPENDED directly, with no further polling
    // to observe it (the poll loop already stopped when the run failed) —
    // reflect that immediately. A RUNNING run's cooperative suspend still
    // takes effect a batch later; the existing poll loop (still running)
    // picks up the eventual "suspended" status itself.
    const isDirectFromFailure = Boolean(autoError);
    setAutoSuspending(true);
    try {
      await api.post(`/api/recon/auto-run/${graphRunId}/suspend`, { reason: "user requested suspend" });
      if (isDirectFromFailure) {
        setAutoSuspending(false);
        setAutoError(null);
        setAutoFailedStep(null);
        setAutoSuspended(true);
      }
    } catch (err) {
      setAutoSuspending(false);
      const detail = err?.response?.data?.detail;
      setAutoError(typeof detail === "string" ? detail : "Could not suspend this run.");
    }
  };

  // Submits a chip tap or typed value identically — the backend validates
  // both against the exact same live options (see interrupts.py) and either
  // progresses, re-asks with fresh chips, completes, or fails; the next poll
  // tick picks up whichever it was. Never restarts the run.
  const resolveInterrupt = async (value) => {
    const graphRunId = graphRunIdRef.current;
    if (!graphRunId || !value) return;
    setResolverBusy(true);
    setResolverError(null);
    try {
      await api.post(`/api/recon/auto-run/${graphRunId}/resolve`, { value });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setResolverError(typeof detail === "string" ? detail : "Could not submit that answer.");
      setResolverBusy(false);
    }
  };

  const startAutoRun = async () => {
    setAutoError(null);
    setAutoFailedStep(null);
    setAutoCurrentStep(null);
    setAutoBatchProgress(null);
    setAutoElapsedMs(0);
    setAutoInterrupt(null);
    setAutoSuspendable(false);
    setAutoSuspending(false);
    setAutoSuspended(false);
    setResolverOpen(false);
    setResolverError(null);
    setResolverBusy(false);
    lastInterruptKeyRef.current = null;
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
      graphRunIdRef.current = graphRunId;
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
    () =>
      buildPreflightRows({
        interfaceIndex,
        identification,
        sheetError,
        selectedInterface,
        sliceLoading,
        sourceSpec,
        targetSpec,
        canAuto,
        canContinueManual,
      }),
    [
      interfaceIndex,
      identification,
      sheetError,
      selectedInterface,
      sliceLoading,
      sourceSpec,
      targetSpec,
      canAuto,
      canContinueManual,
    ]
  );

  const fileMetaText = interfaceIndex
    ? [
        interfaceIndex.file?.size != null
          ? `${Math.round(interfaceIndex.file.size / 1024)} KB`
          : null,
        `${interfaces.length} ${interfaceIndex.indexed ? "interface" : "sheet"}${interfaces.length === 1 ? "" : "s"}`,
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

              {!interfaceIndex ? (
                <>
                  <p className="wizard-field__help" style={{ marginTop: 0 }}>
                    Upload a mapping workbook to auto-detect its interfaces, connectors, fields,
                    entities and join. A single-sheet file is taken as one interface directly.
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
                    <span className="ct-file-row__name" title={interfaceIndex.filename}>
                      {interfaceIndex.filename ?? "mapping sheet"}
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

                  {sliceLoading && (
                    <p className="wizard-field__help" style={{ marginTop: 0 }}>
                      <Loader2 size={12} className="animate-spin" aria-hidden /> Reading the
                      selected interface&apos;s sheet…
                    </p>
                  )}

                  {/* What the index read itself found wrong: no index sheet, a
                      duplicated IBP Record, interfaces with no worksheet. */}
                  {(interfaceIndex.warnings ?? []).map((warning, i) => (
                    <Alert variant="warning" key={i}>
                      {warning}
                    </Alert>
                  ))}

                  {identification?.degraded && identification.degraded_reason && (
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

          {/* The interface-scoping contract, stated plainly: exactly one
              worksheet reaches interpretation. For a workbook that means the
              rest is discarded here; for a one-sheet upload there is no rest,
              so claiming a discard would be untrue. */}
          {selectedInterface?.sheet && (
            <section className="ct-card">
              <div className="ct-card__body ct-scope-note">
                <FileSpreadsheet className="ct-scope-note__icon" aria-hidden />
                <p className="ct-scope-note__text">
                  {singleSheet ? (
                    <>
                      {interfaceIndex.filename ?? "This upload"} holds a single sheet, so it is
                      the dataset: <strong>&ldquo;{selectedInterface.sheet}&rdquo;</strong> is
                      sent straight for connector, entity and join interpretation.
                    </>
                  ) : (
                    <>
                      Only the <strong>&ldquo;{selectedInterface.sheet}&rdquo;</strong> sheet is
                      extracted and sent for connector, entity and join interpretation. The rest
                      of {interfaceIndex.filename ?? "the workbook"} is discarded at this step.
                    </>
                  )}
                </p>
              </div>
            </section>
          )}
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
                {singleInterface ? (
                  // One interface in the workbook — there is no choice to make,
                  // so it's stated rather than offered as a dropdown of one.
                  <div className="ct-file-row">
                    <FileSpreadsheet className="ct-file-row__icon" aria-hidden />
                    <span className="ct-file-row__name">{interfaces[0].record}</span>
                  </div>
                ) : (
                  <Select
                    id="comparison-type-select"
                    value={selectedId}
                    onChange={handleChange}
                    disabled={!interfaceIndex || sliceLoading}
                    options={[
                      {
                        value: "",
                        label: interfaceIndex
                          ? "Select a dataset type…"
                          : "Parse a mapping sheet first",
                      },
                      // Interfaces whose worksheet couldn't be resolved stay
                      // listed but unselectable — an incomplete workbook should
                      // be visible, not silently shortened.
                      ...interfaces.map((iface) => ({
                        value: iface.id,
                        label:
                          iface.status === "ok"
                            ? iface.record
                            : `${iface.record} — ${brokenReason(iface)}`,
                        disabled: iface.status !== "ok",
                      })),
                    ]}
                  />
                )}
                {state.comparisonType && (
                  <div className="wizard-dataset-summary">
                    <Badge variant="success">Selected</Badge>
                    <span>{state.comparisonType.label}</span>
                  </div>
                )}

                {/* Run-level flag, unchecked by default: gates ONLY the
                    data-level value-pairing stage on the Mapping step (never
                    the header-binding-only chain compile, which always
                    runs). See TransformationSpecStep's runValueMapping. */}
                <label className="wizard-use-data">
                  <input
                    type="checkbox"
                    checked={Boolean(state.useData)}
                    onChange={(e) =>
                      dispatch({ type: WizardActions.SET_USE_DATA, useData: e.target.checked })
                    }
                  />
                  <span className="wizard-use-data__label">Use data</span>
                </label>
                <p className="wizard-field__help" style={{ marginTop: 0 }}>
                  {state.useData
                    ? "AI value-pairing will send distinct source/target values to the AI provider to resolve value-level crosswalks."
                    : "Only the mapping sheet's text and column headers are sent to AI — no data values. Fields needing a value-level crosswalk are flagged as pending on the Mapping step."}
                </p>
              </div>

              {/* ── Run mode: segmented Manual/Automatic + single Start action ── */}
              <div className="ct-runmode">
                <p className="wizard-field__label">Run mode</p>

                {autoRunning ? (
                  <div className="wizard-auto-progress">
                    {autoInterrupt ? (
                      <Sparkles size={16} aria-hidden />
                    ) : (
                      <Loader2 size={16} className="animate-spin" aria-hidden />
                    )}
                    <span className="wizard-auto-progress__step">
                      {autoInterrupt
                        ? `Needs your input — ${AUTO_STEP_LABELS[autoCurrentStep] ?? "resolving"}`
                        : AUTO_STEP_LABELS[autoCurrentStep] ?? "Starting…"}
                      {autoCurrentStep === "run_batches" && autoBatchProgress && (
                        <>
                          {" "}— {autoBatchProgress.batches_completed ?? autoBatchProgress.batch_index}/
                          {autoBatchProgress.batch_count} batches done (batch{" "}
                          {autoBatchProgress.batch_index + 1} of {autoBatchProgress.batch_count},{" "}
                          {autoBatchProgress.batch_label}
                          {autoBatchProgress.stage
                            ? `: ${AUTO_BATCH_STAGE_LABELS[autoBatchProgress.stage] ?? autoBatchProgress.stage}`
                            : ""}
                          )
                        </>
                      )}
                    </span>
                    <span className="wizard-auto-progress__timer">{formatElapsed(autoElapsedMs)}</span>
                    {autoInterrupt && !resolverOpen && (
                      <button
                        type="button"
                        className="wizard-link"
                        onClick={() => setResolverOpen(true)}
                      >
                        Reopen
                      </button>
                    )}
                    {autoSuspendable && !autoInterrupt && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={suspendAutoRun}
                        disabled={autoSuspending}
                      >
                        {autoSuspending ? "Suspending…" : "Suspend"}
                      </Button>
                    )}
                  </div>
                ) : autoSuspended ? (
                  <Alert variant="info">
                    Run suspended — its progress is saved. Resume it anytime from{" "}
                    <a href="/stored-runs">Stored Runs</a>.
                    <div className="wizard-instructions__actions" style={{ marginTop: 8 }}>
                      <Button variant="secondary" size="sm" onClick={startAutoRun}>
                        Start a new run instead
                      </Button>
                    </div>
                  </Alert>
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
                      {autoSuspendable && (
                        <Button variant="outline" size="sm" onClick={suspendAutoRun} disabled={autoSuspending}>
                          {autoSuspending ? "Suspending…" : "Suspend for later"}
                        </Button>
                      )}
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

      <ResolverPanel
        open={resolverOpen}
        interrupt={autoInterrupt}
        busy={resolverBusy}
        error={resolverError}
        onSubmit={resolveInterrupt}
        onClose={() => setResolverOpen(false)}
      />
    </StepShell>
  );
}

export default ComparisonTypeStep;
