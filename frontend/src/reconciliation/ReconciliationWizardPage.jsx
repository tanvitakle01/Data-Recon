import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { useWizard } from "./context/useWizard";
import { WIZARD_STEPS, getStepByKey } from "./steps/stepConfig";
import StepRoute from "./components/StepRoute";
import ConnectorSelectionStep from "./steps/ConnectorSelectionStep";
import ComparisonTypeStep from "./steps/ComparisonTypeStep";
import TransformationSpecStep from "./steps/TransformationSpecStep";
import MappingReviewPage from "./steps/MappingReviewPage";
import DatasetDetailPreviewPage from "./steps/DatasetDetailPreviewPage";
import ReconciliationRunStep from "./steps/ReconciliationRunStep";
import "./reconciliationWizard.css";

// The detailed dataset preview is a sub-page of a connector step (source or
// target). Gate it by that role's stepKey so it inherits the same lock rules
// and keeps the stepper highlighting the right step.
function DatasetPreviewRoute() {
  const { role } = useParams();
  const stepKey = role === "target" ? "target" : "source";
  return (
    <StepRoute stepKey={stepKey}>
      <DatasetDetailPreviewPage />
    </StepRoute>
  );
}

// Bare "/reconciliation" (or an unknown sub-path) resumes wherever the
// draft left off instead of always restarting at Step 1.
function WizardIndexRedirect() {
  const { state } = useWizard();
  const current = getStepByKey(state.step) ?? WIZARD_STEPS[0];
  return <Navigate to={`/reconciliation/${current.path}`} replace />;
}

function ReconciliationWizardContent() {
  return (
    <div className="wizard-shell">
      <div className="wizard-content">
        <Routes>
          <Route index element={<WizardIndexRedirect />} />
          {/*
            Distinct `key` per role is REQUIRED. Both routes render
            ConnectorSelectionStep at the same position in the <Routes> outlet;
            without a key React reuses one instance across source↔target and
            the child FileUploadCard/SapFetchPanel keep their local file state,
            leaking one side's file into the other. The key forces a full
            remount per role so source and target uploads stay isolated.
          */}
          <Route
            path="source"
            element={
              <StepRoute stepKey="source">
                <ConnectorSelectionStep key="connector-source" role="source" />
              </StepRoute>
            }
          />
          <Route
            path="target"
            element={
              <StepRoute stepKey="target">
                <ConnectorSelectionStep key="connector-target" role="target" />
              </StepRoute>
            }
          />
          <Route
            path="comparison-type"
            element={
              <StepRoute stepKey="comparisonType">
                <ComparisonTypeStep />
              </StepRoute>
            }
          />
          <Route
            path="transformation-spec"
            element={
              <StepRoute stepKey="transformationSpec">
                <TransformationSpecStep />
              </StepRoute>
            }
          />
          {/*
            Mapping Review is a sub-flow reached from Step 4's "Run
            Deterministic Mapping" button, NOT one of the 6 numbered wizard
            steps — it's still gated by stepKey="transformationSpec" (so it
            can't be reached before Step 4 unlocks) and keeps state.step ==
            "transformationSpec", so the stepper continues to show Step 4 as
            current while this page is open.
          */}
          <Route
            path="transformation-spec/mapping-review"
            element={
              <StepRoute stepKey="transformationSpec">
                <MappingReviewPage />
              </StepRoute>
            }
          />
          <Route path="dataset-preview/:role" element={<DatasetPreviewRoute />} />
          <Route
            path="reconciliation"
            element={
              <StepRoute stepKey="reconciliation">
                <ReconciliationRunStep />
              </StepRoute>
            }
          />
          <Route path="*" element={<WizardIndexRedirect />} />
        </Routes>
      </div>
    </div>
  );
}

function ReconciliationWizardPage() {
  // WizardProvider now wraps the whole app (see App.jsx) so the persistent
  // sidebar can read wizard state; this page just renders the routed step.
  return <ReconciliationWizardContent />;
}

export default ReconciliationWizardPage;
