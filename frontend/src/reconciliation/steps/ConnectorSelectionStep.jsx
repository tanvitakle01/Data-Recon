import { useEffect, useMemo, useState } from "react";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import StepShell from "../components/StepShell";
import SubStagePills from "../components/SubStagePills";
import DatasetPreviewCard from "../components/DatasetPreviewCard";
import FileUploadCard from "../../components/FileUploadCard";
import { EXCEL_OPTION } from "../lib/connectorOptions";

const FILE_STAGE_LABELS = ["Upload Dataset", "Dataset Preview"];

// Renders identically for role="source" and role="target". File upload is the
// only supported connector for Stage 1 — no live connectors — so this step
// auto-assigns the Excel connector and goes straight to Upload → Preview.
function ConnectorSelectionStep({ role }) {
  const { state, dispatch } = useWizard();
  const roleState = state[role];
  const roleLabel = role === "source" ? "Source" : "Target";

  const [showUploadAgain, setShowUploadAgain] = useState(false);

  useEffect(() => {
    if (!roleState.connectorId) {
      dispatch({
        type: WizardActions.SET_CONNECTOR,
        role,
        connectorId: EXCEL_OPTION.id,
        kind: EXCEL_OPTION.kind,
      });
    }
  }, [roleState.connectorId, role, dispatch]);

  const logAssignment = (kind, filename, rowCount) => {
    const isReplacement = Boolean(roleState.dataset);
    console.debug(
      `[wizard] ${isReplacement ? "FILE REPLACEMENT" : "DATASET ASSIGNMENT"} ` +
        `| role=${role} | connector=${kind} | file=${filename} | rows=${rowCount}` +
        (isReplacement ? ` | previous=${roleState.dataset?.filename}` : ""),
    );
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

  const canContinue = useMemo(() => Boolean(roleState.dataset), [roleState.dataset]);

  if (!roleState.connectorId) {
    return <StepShell stepKey={role} canContinue={canContinue} />;
  }

  const showPreviewCard = Boolean(roleState.dataset) && !showUploadAgain;
  return (
    <StepShell stepKey={role} canContinue={canContinue}>
      <SubStagePills stages={FILE_STAGE_LABELS} activeIndex={showPreviewCard ? 1 : 0} />

      {showPreviewCard ? (
        <DatasetPreviewCard dataset={roleState.dataset} onReplaceFile={() => setShowUploadAgain(true)} />
      ) : (
        <div className="wizard-connector-panel">
          <FileUploadCard key={`upload-${role}`} title={`${roleLabel} File`} onLoaded={handleExcelLoaded} />
        </div>
      )}
    </StepShell>
  );
}

export default ConnectorSelectionStep;
