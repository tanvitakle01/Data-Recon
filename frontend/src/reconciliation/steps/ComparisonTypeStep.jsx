import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../../services/api";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import StepShell from "../components/StepShell";
import { getVisibleSteps, getStepByKey } from "./stepConfig";
import Chevron from "../components/Chevron";
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
} from "lucide-react";

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
              {spec.ambiguous.length > 4 ? "…" : ""}) — not resolved automatically.
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
        ? `${unresolvedCount} unresolved, ${ambiguousCount} ambiguous — not resolved automatically.`
        : "All named entities exist on their connector.",
  });

  rows.push({
    status: canContinueManual ? "pass" : "pending",
    name: "Ready to run",
    detail: canContinueManual
      ? "Continue through Source, Target and Mapping."
      : "Select a dataset type to continue.",
  });

  return rows;
}

function ComparisonTypeStep() {
  const { state, dispatch } = useWizard();
  const selectedId = state.comparisonType?.id ?? "";
  const identification = state.sheetIdentification;
  const interfaceIndex = state.interfaceIndex;
  const parsedMappingSheet = state.transformationSpec?.parsedMappingSheet;

  // Detection details and Pre-flight checks are both collapsed by default —
  // their content is derived/secondary to the mapping-sheet summary above,
  // so hiding them behind a dropdown keeps the column from feeling crowded.
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [preflightOpen, setPreflightOpen] = useState(false);

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
  // The chosen interface's own sheet being read. Separate from sheetLoading
  // (the workbook index read) because they are separate phases: the index
  // read only ever yields the interface list.
  const [sliceLoading, setSliceLoading] = useState(false);
  // Connector/entity/field identification (/mapping-sheet/identify) is a
  // SEPARATE, optional step — it never fires automatically. The parsed sheet
  // is stored and forwarded to Step 4 (mapping resolution) regardless of
  // whether this ever runs; only "Resolve data connections" below issues it.
  const [resolveLoading, setResolveLoading] = useState(false);
  const [resolveError, setResolveError] = useState(null);

  // Slice ONE interface out of the workbook and parse only that slice
  // (deterministic, scoped to that worksheet). Interpretation (identify) is
  // no longer chained here — see resolveConnections.
  const selectInterface = async (iface, index = interfaceIndex) => {
    dispatch({ type: WizardActions.CLEAR_SHEET_IDENTIFICATION });
    setResolveError(null);
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
      // This is the ONLY thing selecting a sheet does automatically now —
      // the mapping sheet is considered "uploaded" from here on regardless of
      // whether connectors ever get resolved.
      dispatch({
        type: WizardActions.SET_PARSED_MAPPING_SHEET,
        parsedMappingSheet: parseRes.data,
      });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setSheetError(
        typeof detail === "string"
          ? detail
          : `Could not read the "${iface.record}" interface.`
      );
    } finally {
      setSliceLoading(false);
    }
  };

  // "Resolve data connections" button: the ONLY trigger for
  // /mapping-sheet/identify. include_entities: the same identification call
  // also returns which entities to fetch per side and any implied join,
  // gated against each side's live entity list — pre-populates the Join
  // Builder canvas. Degrades gracefully, so a failure here never blocks the
  // wizard: the user just selects connectors manually on Steps 2/3, and
  // whatever was already parsed keeps flowing to Step 4 either way.
  const resolveConnections = async () => {
    if (!parsedMappingSheet || !selectedInterface) return;
    setResolveError(null);
    setResolveLoading(true);
    try {
      const idRes = await api.post("/api/recon/mapping-sheet/identify", {
        mapping_sheet: parsedMappingSheet,
        include_entities: true,
      });
      dispatch({
        type: WizardActions.SET_SHEET_IDENTIFICATION,
        identification: {
          ...idRes.data,
          sheet: { name: interfaceIndex?.filename, size: interfaceIndex?.file?.size },
          // Which interface this identification came from — the rest of the
          // workbook played no part in it.
          interface: {
            id: selectedInterface.id,
            record: selectedInterface.record,
            sheet: selectedInterface.sheet,
          },
          parsed: parsedMappingSheet,
        },
      });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setResolveError(
        typeof detail === "string"
          ? detail
          : `Could not resolve data connections for "${selectedInterface.record}".`
      );
    } finally {
      setResolveLoading(false);
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

  // ── Replaces the shell's generic Continue button ────────────────────────
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

                  {/* Optional, explicit trigger for /mapping-sheet/identify.
                      The sheet above is already parsed and stored (feeding
                      Step 4) whether or not this is ever clicked. */}
                  <div className="ct-resolve-row">
                    <Button
                      variant={hasIdentification ? "outline" : "primary"}
                      size="sm"
                      onClick={resolveConnections}
                      disabled={!parsedMappingSheet || sliceLoading || resolveLoading}
                    >
                      {resolveLoading ? (
                        <>
                          <Loader2 size={12} className="animate-spin" aria-hidden /> Resolving…
                        </>
                      ) : hasIdentification ? (
                        "Re-resolve data connections"
                      ) : (
                        "Resolve data connections"
                      )}
                    </Button>
                    {!parsedMappingSheet && !sliceLoading && (
                      <span className="wizard-field__help">
                        Select a dataset type above to enable.
                      </span>
                    )}
                  </div>
                  {resolveError && <Alert variant="error">{resolveError}</Alert>}

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

          {/* Detection details: collapsed behind a dropdown — the compact
              summary above already covers the common case. */}
          {hasIdentification && (
            <section className="ct-card">
              <div
                className="ct-card__head ct-card__head--toggle"
                role="button"
                tabIndex={0}
                aria-expanded={detailsOpen}
                onClick={() => setDetailsOpen((open) => !open)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setDetailsOpen((open) => !open);
                  }
                }}
              >
                <h3 className="ct-card__title">Detection details</h3>
                <span className="ct-card__spacer" />
                <Chevron open={detailsOpen} />
              </div>
              {detailsOpen && (
                <div className="ct-card__body">
                  <DetectionDetails state={state} identification={identification} />
                </div>
              )}
            </section>
          )}

          <section className="ct-card ct-card--tint-yellow">
            <div
              className="ct-card__head ct-card__head--toggle"
              role="button"
              tabIndex={0}
              aria-expanded={preflightOpen}
              onClick={() => setPreflightOpen((open) => !open)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setPreflightOpen((open) => !open);
                }
              }}
            >
              <h3 className="ct-card__title">Pre-flight checks</h3>
              <span className="ct-card__spacer" />
              <Chevron open={preflightOpen} />
            </div>
            {preflightOpen && (
              <div className="ct-card__body ct-card__body--flush">
                {preflightRows.map((row) => (
                  <PreflightRow key={row.name} {...row} />
                ))}
              </div>
            )}
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
              </div>

              <div className="ct-runmode">
                <p className="wizard-field__label">Run mode</p>
                <p className="wizard-field__help">
                  Step through source, target and mapping with approval at each step.
                </p>
                <Button variant="primary" onClick={handleManualContinue} disabled={!canContinueManual}>
                  Start
                </Button>
              </div>
            </div>
          </section>
        </div>
      </div>
    </StepShell>
  );
}

export default ComparisonTypeStep;
