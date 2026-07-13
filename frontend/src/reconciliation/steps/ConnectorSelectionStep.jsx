import { useMemo, useState } from "react";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import StepShell from "../components/StepShell";
import SubStagePills from "../components/SubStagePills";
import DatasetPreviewCard from "../components/DatasetPreviewCard";
import IbpDatasetWorkspace from "../connectors/IbpDatasetWorkspace";
import S4DatasetWorkspace from "../connectors/S4DatasetWorkspace";
import FileUploadCard from "../../components/FileUploadCard";

// `roles` declares which side(s) a connector is available for. Excel is
// available for both; S/4HANA is a source system, IBP is a target system.
// Anything with an empty `roles` renders as "Coming soon".
const CONNECTOR_OPTIONS = [
  { id: "excel_upload", label: "Excel Upload", category: "File", kind: "excel", roles: ["source", "target"] },
  { id: "csv_upload", label: "CSV Upload", category: "File", kind: "csv", roles: [] },
  { id: "sap_s4hana", label: "SAP S/4HANA", category: "SAP", kind: "s4", roles: ["source"] },
  { id: "sap_ecc", label: "SAP ECC", category: "SAP", kind: "ecc", roles: [] },
  { id: "sap_bw", label: "SAP BW", category: "SAP", kind: "bw", roles: [] },
  { id: "sap_ibp", label: "SAP IBP", category: "SAP", kind: "ibp", roles: ["target"] },
  { id: "custom", label: "Custom Connector", category: "Custom", kind: "custom", roles: [] },
];

const SAP_STAGE_LABELS = ["Select Connector", "Connect & Load Metadata", "Build Dataset", "Preview"];
const FILE_STAGE_LABELS = ["Upload Dataset", "Dataset Preview"];
const SAP_STAGE_INDEX = { connect: 1, build: 2, preview: 3 };

// Renders identically for role="source" and role="target" — the same
// progressive sequence of cards either way: pick a connector, then (for
// files) upload-and-preview, or (for SAP) connect, build the dataset, and
// preview it. Each stage shows only the controls relevant to it.
function ConnectorSelectionStep({ role }) {
  const { state, dispatch } = useWizard();
  const roleState = state[role];
  const roleLabel = role === "source" ? "Source" : "Target";

  // Local, UI-only navigation — never persisted, never touches the reducer.
  // "Replace File" flips this back to the upload card without discarding the
  // dataset until a new file is actually chosen.
  const [showUploadAgain, setShowUploadAgain] = useState(false);
  // Mirrors the SAP workspace's internal card ("connect" | "build" |
  // "preview") purely so the pills above it stay in sync; the workspace is
  // the source of truth and reports changes via onStageChange.
  const [sapStage, setSapStage] = useState("connect");

  const isFileKind = roleState.kind === "excel" || roleState.kind === "csv";
  const isSapKind = roleState.kind === "s4" || roleState.kind === "ibp";

  // Distinguish a first-time assignment from a replacement, purely for logs.
  const logAssignment = (kind, filename, rowCount) => {
    const isReplacement = Boolean(roleState.dataset);
    console.debug(
      `[wizard] ${isReplacement ? "FILE REPLACEMENT" : "DATASET ASSIGNMENT"} ` +
        `| role=${role} | connector=${kind} | file=${filename} | rows=${rowCount}` +
        (isReplacement ? ` | previous=${roleState.dataset?.filename}` : ""),
    );
  };

  const handleSelectConnector = (option) => {
    setShowUploadAgain(false);
    setSapStage("connect");
    dispatch({
      type: WizardActions.SET_CONNECTOR,
      role,
      connectorId: option.id,
      kind: option.kind,
    });
  };

  const handleChangeConnector = () => {
    if (roleState.dataset) {
      const proceed = window.confirm(
        `Changing the connector will discard the ${roleLabel.toLowerCase()} dataset you've already built. Continue?`
      );
      if (!proceed) return;
    }
    setShowUploadAgain(false);
    setSapStage("connect");
    dispatch({ type: WizardActions.RESET_ROLE, role });
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

  // ---- Card 1: connector grid — hidden once a connector is chosen ----
  if (!roleState.connectorId) {
    return (
      <StepShell stepKey={role} canContinue={canContinue}>
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

  // ---- Excel / CSV: 2-card flow (Upload Dataset → Dataset Preview) ----
  if (isFileKind) {
    const showPreviewCard = Boolean(roleState.dataset) && !showUploadAgain;
    return (
      <StepShell stepKey={role} canContinue={canContinue}>
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
            {/* key ties this upload card to its role so its local file state
                can never be reused across source/target. */}
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
  // Cards 2-4 (connect / build / preview) are owned entirely by the
  // workspace component; it reports which one is active via onStageChange
  // purely so the pills above it stay in sync. ----
  if (isSapKind) {
    const activeIndex = roleState.dataset ? 3 : SAP_STAGE_INDEX[sapStage] ?? 1;
    return (
      <StepShell stepKey={role} canContinue={canContinue}>
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
          />
        )}
        {roleState.kind === "ibp" && (
          <IbpDatasetWorkspace
            key={`ibp-${role}`}
            dataset={roleState.dataset}
            onLoaded={handleSapLoaded}
            onStageChange={setSapStage}
          />
        )}
      </StepShell>
    );
  }

  // Any other/unrecognized kind (shouldn't be reachable — every enabled
  // CONNECTOR_OPTIONS entry is excel/csv or s4/ibp).
  return <StepShell stepKey={role} canContinue={canContinue} />;
}

export default ConnectorSelectionStep;
