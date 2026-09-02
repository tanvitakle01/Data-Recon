import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import StepShell from "../components/StepShell";
import SubStagePills from "../components/SubStagePills";
import DatasetPreviewCard from "../components/DatasetPreviewCard";
import IbpDatasetWorkspace from "../connectors/IbpDatasetWorkspace";
import S4DatasetWorkspace from "../connectors/S4DatasetWorkspace";
import FileUploadCard from "../../components/FileUploadCard";
import {
  CONNECTOR_OPTIONS,
  EXCEL_OPTION,
  liveFetchOptionFor,
} from "../lib/connectorOptions";
import { effectiveEntityJoin } from "../lib/entityJoinSpec";
import { ConfirmDialog, Alert } from "@bristlecone/canopy";

const SAP_STAGE_LABELS = ["Select Connector", "Connect & Load Metadata", "Build Dataset", "Preview"];
const FILE_STAGE_LABELS = ["Upload Dataset", "Dataset Preview"];
const SAP_STAGE_INDEX = { connect: 1, build: 2, preview: 3 };

// Renders identically for role="source" and role="target". The connector step
// now opens on a binary Excel-Upload vs Live-Fetch choice; Live Fetch resolves
// to the connector the mapping sheet identified (or the sole configured live
// connector for this role) behind ONE explicit confirmation citing the
// evidence — a wrong connector silently fetches entirely wrong data, so this
// click is required even though field selection later is toggle-only. An
// override reveals the full connector grid (unchanged legacy behavior).
function ConnectorSelectionStep({ role }) {
  const { state, dispatch } = useWizard();
  const navigate = useNavigate();
  const roleState = state[role];
  const roleLabel = role === "source" ? "Source" : "Target";
  const openDetailedPreview = () => navigate(`/reconciliation/dataset-preview/${role}`);

  // Sheet-driven identification for THIS side (may be null / unidentified).
  const idSide = role === "source" ? state.sheetIdentification?.source : state.sheetIdentification?.target;

  // Local, UI-only navigation — never persisted, never touches the reducer.
  const [showUploadAgain, setShowUploadAgain] = useState(false);
  const [sapStage, setSapStage] = useState("connect");
  // Pre-connector screens (only meaningful before a connector is chosen):
  // "choose" → binary Excel/Live-Fetch, "confirm" → Live-Fetch confirmation,
  // "grid" → full legacy connector grid (override target).
  const [preScreen, setPreScreen] = useState("choose");
  // Change-connector confirmation gate (replaces window.confirm) — only shown
  // when a dataset was already built, since discarding it is destructive.
  const [changeConfirmOpen, setChangeConfirmOpen] = useState(false);

  const isFileKind = roleState.kind === "excel" || roleState.kind === "csv";
  const isSapKind = roleState.kind === "s4" || roleState.kind === "ibp";

  // The connector Live Fetch will use: the sheet-identified one when confident
  // and available for this role, else the sole configured live connector.
  const identifiedOption = useMemo(() => {
    if (!idSide?.connector_id) return null;
    const opt = CONNECTOR_OPTIONS.find((o) => o.id === idSide.connector_id);
    return opt && opt.roles.includes(role) ? opt : null;
  }, [idSide, role]);
  const liveOption = identifiedOption ?? liveFetchOptionFor(role);

  // Fields the sheet says to compare on this side — pre-selected (and
  // validated against live schema) inside the workspace. Toggle-only there.
  const preselectFields = idSide?.fields ?? [];

  // Entities/join for THIS side: the Step-1 free-text instruction if the user
  // typed one, else whatever the mapping sheet derived (the precedence lives in
  // effectiveEntityJoin). Already existence-gated server-side against this
  // side's own connector. It PRE-POPULATES the Join Builder canvas below — the
  // canvas still owns the join defaults and stays fully editable.
  const prepopulate = useMemo(
    () => effectiveEntityJoin(state, role),
    [state, role]
  );

  const logAssignment = (kind, filename, rowCount) => {
    const isReplacement = Boolean(roleState.dataset);
    console.debug(
      `[wizard] ${isReplacement ? "FILE REPLACEMENT" : "DATASET ASSIGNMENT"} ` +
        `| role=${role} | connector=${kind} | file=${filename} | rows=${rowCount}` +
        (isReplacement ? ` | previous=${roleState.dataset?.filename}` : ""),
    );
  };

  const handleSelectConnector = (option) => {
    if (!option) return;
    setShowUploadAgain(false);
    setSapStage("connect");
    setPreScreen("choose");
    dispatch({
      type: WizardActions.SET_CONNECTOR,
      role,
      connectorId: option.id,
      kind: option.kind,
    });
  };

  const performChangeConnector = () => {
    setShowUploadAgain(false);
    setSapStage("connect");
    setPreScreen("choose");
    dispatch({ type: WizardActions.RESET_ROLE, role });
  };

  const handleChangeConnector = () => {
    if (roleState.dataset) {
      setChangeConfirmOpen(true);
      return;
    }
    performChangeConnector();
  };

  const handleExcelLoaded = (data, file, meta) => {
    if (!data) {
      console.debug(`[wizard] RESET_ROLE | role=${role} (upload cleared/failed)`);
      dispatch({ type: WizardActions.RESET_ROLE, role });
      return;
    }
    logAssignment("excel", data.filename, data.rows);
    setShowUploadAgain(false);
    dispatch({
      type: WizardActions.SET_DATASET,
      role,
      dataset: {
        datasetId: `${role}-excel-${Date.now()}`,
        filename: data.filename,
        columns: data.columns ?? [],
        preview: data.preview ?? [],
        rowCount: data.rows,
        colCount: data.cols,
        rows: null,
        file,
        sheet: meta?.sheet_name ?? null,
        sheets: meta?.sheets ?? [],
        fetchedAt: new Date().toISOString(),
      },
    });
  };

  const handleSapLoaded = ({ columns, preview, rows, rowCount }) => {
    const filename = `${roleState.connectorId === "sap_s4hana" ? "SAP S/4HANA" : "SAP IBP"} live fetch`;
    logAssignment(roleState.kind, filename, rowCount);
    dispatch({
      type: WizardActions.SET_DATASET,
      role,
      dataset: {
        datasetId: `${role}-${roleState.kind}-${Date.now()}`,
        filename,
        kind: roleState.kind,
        columns,
        preview,
        rowCount,
        colCount: columns.length,
        rows,
        file: null,
        sheet: null,
        sheets: [],
        fetchedAt: new Date().toISOString(),
      },
    });
  };

  const canContinue = useMemo(() => Boolean(roleState.dataset), [roleState.dataset]);

  // Rendered in the branches that expose "Change Connector"/"Back to
  // Connectors". Discarding a built dataset is destructive, so it uses the
  // destructive variant.
  const changeConnectorDialog = (
    <ConfirmDialog
      isOpen={changeConfirmOpen}
      variant="destructive"
      title="Change connector?"
      message={`Changing the connector will discard the ${roleLabel.toLowerCase()} dataset you've already built. Continue?`}
      confirmText="Discard & change"
      cancelText="Keep dataset"
      onConfirm={() => {
        setChangeConfirmOpen(false);
        performChangeConnector();
      }}
      onCancel={() => setChangeConfirmOpen(false)}
    />
  );

  // ============ Pre-connector screens (no connector chosen yet) ============
  if (!roleState.connectorId) {
    // ---- Override target: the full legacy connector grid (unchanged) ----
    if (preScreen === "grid") {
      return (
        <StepShell stepKey={role} canContinue={canContinue}>
          <button type="button" className="wizard-link" onClick={() => setPreScreen("choose")}>
            ← Back
          </button>
          <div className="wizard-option-grid">
            {CONNECTOR_OPTIONS.map((option) => {
              const available = option.roles.includes(role);
              return (
                <button
                  key={option.id}
                  type="button"
                  className={`wizard-option-card ${!available ? "is-disabled" : ""}`}
                  onClick={() => available && handleSelectConnector(option)}
                  disabled={!available}
                >
                  <span className="wizard-option-card__label">{option.label}</span>
                  <span className="wizard-option-card__meta">{option.category}</span>
                  {!available && <span className="wizard-option-card__badge">Coming soon</span>}
                </button>
              );
            })}
          </div>
        </StepShell>
      );
    }

    // ---- Live-Fetch confirmation: the ONE required connector click ----
    if (preScreen === "confirm") {
      const fromSheet = Boolean(idSide?.kind && identifiedOption);
      const evidence = fromSheet
        ? idSide.evidence
        : `Only configured live connector for the ${roleLabel.toLowerCase()} side.`;
      return (
        <StepShell stepKey={role} canContinue={canContinue}>
          <div className="wizard-connector-confirm">
            <p className="wizard-connector-confirm__title">
              Live Fetch will connect to <strong>{liveOption?.label ?? "—"}</strong>
            </p>
            {evidence && (
              <p className="wizard-connector-confirm__evidence">
                {fromSheet ? "Detected from your mapping sheet: " : ""}
                {evidence}
              </p>
            )}
            {idSide && !idSide.kind && (
              <Alert variant="warning" style={{ marginTop: 8 }}>
                The mapping sheet didn't clearly identify the {roleLabel.toLowerCase()} system
                {idSide.evidence ? ` (${idSide.evidence})` : ""} — confirm carefully.
              </Alert>
            )}
            <div className="wizard-connector-confirm__actions">
              <button
                type="button"
                className="wizard-btn wizard-btn--primary"
                onClick={() => handleSelectConnector(liveOption)}
              >
                Confirm &amp; Continue
              </button>
              <button
                type="button"
                className="wizard-link"
                onClick={() => setPreScreen("grid")}
              >
                Override — choose a different connector
              </button>
              <button
                type="button"
                className="wizard-link"
                onClick={() => setPreScreen("choose")}
              >
                Back
              </button>
            </div>
          </div>
        </StepShell>
      );
    }

    // ---- Default: binary Excel-Upload vs Live-Fetch choice ----
    return (
      <StepShell stepKey={role} canContinue={canContinue}>
        <div className="wizard-source-choice">
          <button
            type="button"
            className="wizard-choice-card"
            onClick={() => handleSelectConnector(EXCEL_OPTION)}
          >
            <span className="wizard-choice-card__label">Excel Upload</span>
            <span className="wizard-choice-card__meta">Upload a spreadsheet you already have</span>
          </button>
          <button
            type="button"
            className="wizard-choice-card"
            onClick={() => setPreScreen("confirm")}
            disabled={!liveOption}
          >
            <span className="wizard-choice-card__label">Live Fetch</span>
            <span className="wizard-choice-card__meta">
              {liveOption ? `Connect to ${liveOption.label}` : "No live connector configured"}
            </span>
            {idSide?.kind && identifiedOption && (
              <span className="wizard-choice-card__badge">Detected from sheet</span>
            )}
          </button>
        </div>
        <button type="button" className="wizard-link" onClick={() => setPreScreen("grid")}>
          See all connectors
        </button>
      </StepShell>
    );
  }

  // ---- Excel / CSV: 2-card flow (Upload Dataset → Dataset Preview) ----
  if (isFileKind) {
    const showPreviewCard = Boolean(roleState.dataset) && !showUploadAgain;
    return (
      <StepShell stepKey={role} canContinue={canContinue}>
        {changeConnectorDialog}
        <SubStagePills stages={FILE_STAGE_LABELS} activeIndex={showPreviewCard ? 1 : 0} />
        <button type="button" className="wizard-link" onClick={handleChangeConnector}>
          ← Back to Connectors
        </button>

        {showPreviewCard ? (
          <DatasetPreviewCard
            dataset={roleState.dataset}
            onReplaceFile={() => setShowUploadAgain(true)}
          />
        ) : (
          <div className="wizard-connector-panel">
            <FileUploadCard
              key={`upload-${role}`}
              title={`${roleLabel} File`}
              onLoaded={handleExcelLoaded}
            />
          </div>
        )}
      </StepShell>
    );
  }

  // ---- SAP S/4HANA & SAP IBP: 4-card flow, identical for both connectors.
  if (isSapKind) {
    const activeIndex = roleState.dataset ? 3 : SAP_STAGE_INDEX[sapStage] ?? 1;
    return (
      <StepShell stepKey={role} canContinue={canContinue}>
        {changeConnectorDialog}
        <SubStagePills stages={SAP_STAGE_LABELS} activeIndex={activeIndex} />
        <button type="button" className="wizard-link" onClick={handleChangeConnector}>
          ← Change Connector
        </button>

        {roleState.kind === "s4" && (
          <S4DatasetWorkspace
            key={`s4-${role}`}
            dataset={roleState.dataset}
            onLoaded={handleSapLoaded}
            onStageChange={setSapStage}
            onOpenDetailedPreview={openDetailedPreview}
            preselectFields={preselectFields}
            prepopulate={prepopulate}
          />
        )}
        {roleState.kind === "ibp" && (
          <IbpDatasetWorkspace
            key={`ibp-${role}`}
            dataset={roleState.dataset}
            onLoaded={handleSapLoaded}
            onStageChange={setSapStage}
            onOpenDetailedPreview={openDetailedPreview}
            preselectFields={preselectFields}
            prepopulate={prepopulate}
          />
        )}
      </StepShell>
    );
  }

  // Any other/unrecognized kind (shouldn't be reachable).
  return <StepShell stepKey={role} canContinue={canContinue} />;
}

export default ConnectorSelectionStep;
