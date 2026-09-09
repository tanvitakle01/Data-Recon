import { useNavigate } from "react-router-dom";
import { Button } from "@bristlecone/canopy";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import { getVisibleSteps } from "../steps/stepConfig";
import { clearWizardDraft } from "../context/wizardPersistence";

// Human label for a connector kind — kept local since it's a one-line lookup.
const CONNECTOR_LABEL = {
  excel: "Excel",
  csv: "CSV",
  s4: "S/4HANA",
  ibp: "SAP IBP",
  ecc: "SAP ECC",
  bw: "SAP BW",
};

// Small, real (never fabricated) sub-label shown under a step's name in the
// horizontal step bar — whatever's already confirmed for that step, or
// nothing yet.
function stepDetail(state, key) {
  if (key === "comparisonType") return state.comparisonType?.label ?? "";
  if (key === "source") return CONNECTOR_LABEL[state.source?.kind] ?? "";
  if (key === "target") return CONNECTOR_LABEL[state.target?.kind] ?? "";
  if (key === "transformationSpec") {
    const mode = state.transformationSpec?.mappingMode;
    return mode === "manual" ? "Manual" : mode === "deterministic" ? "AI-mapping" : "";
  }
  if (key === "reconciliation") return state.reconciliation ? "Completed" : "";
  return "";
}

function StepShell({
  stepKey,
  children,
  canContinue = true,
  continueLabel = "Continue",
  // When true, the footer shows only Back. Used by steps that advance via
  // their own primary action (e.g. the Mapping step's "Run Reconciliation")
  // rather than a generic Continue, so there's no second, run-skipping path.
  hideContinue = false,
}) {
  const { state, dispatch } = useWizard();
  const navigate = useNavigate();

  // Position/neighbours are computed over the steps actually shown for the
  // current engine, so hidden steps (e.g. Review Changes in the script flow)
  // are skipped by Back/Continue and the "Step N of M" counter stays correct.
  const steps = getVisibleSteps(state.transformationSpec?.useScriptTransformations);
  const index = steps.findIndex((s) => s.key === stepKey);
  const step = steps[index];
  const prevStep = steps[index - 1];
  const nextStep = steps[index + 1];

  const goToStep = (target) => {
    dispatch({ type: WizardActions.GO_TO_STEP, step: target.key });
    navigate(`/reconciliation/${target.path}`);
  };

  // Jumping via the step bar (unlike Back/Continue, which only ever move to an
  // adjacent step) can target any step, so it needs its own lock check.
  const jumpToStep = (target) => {
    if (state.stepStatus[target.key] === "locked") return;
    goToStep(target);
  };

  const handleBack = () => {
    if (prevStep) goToStep(prevStep);
  };

  const handleContinue = () => {
    dispatch({ type: WizardActions.COMPLETE_STEP, step: stepKey });
    if (nextStep) goToStep(nextStep);
  };

  // Discards all wizard progress (in-memory state AND the persisted
  // sessionStorage draft — see wizardPersistence.js) and returns to Step 1.
  // Confirmed first since this can't be undone: a restarted server or a
  // reloaded page otherwise silently rehydrates the old draft, which is
  // exactly the confusion this button exists to let someone escape from.
  const handleStartOver = () => {
    if (!window.confirm("Start over? This discards all progress in this wizard.")) return;
    clearWizardDraft();
    dispatch({ type: WizardActions.RESET_WIZARD });
    navigate(`/reconciliation/${steps[0].path}`);
  };

  return (
    <section className="wizard-step">
      <header className="wizard-step__header">
        <div className="wizard-step__header-row">
          <p className="wizard-step__eyebrow">
            Step {index + 1} of {steps.length}
          </p>
          <button type="button" className="wizard-link wizard-step__start-over" onClick={handleStartOver}>
            Start Over
          </button>
        </div>
        <h2 className="wizard-step__title">{step?.label}</h2>
        <p className="wizard-step__desc">{step?.description}</p>
      </header>

      <nav className="ct-stepbar" aria-label="Wizard steps">
        {steps.map((s, i) => {
          const status = state.stepStatus[s.key];
          const isActive = s.key === stepKey;
          const done = status === "complete";
          const detail = stepDetail(state, s.key);
          return (
            <button
              key={s.key}
              type="button"
              className={`ct-stepbar__step ${isActive ? "is-active" : ""} ${done ? "is-done" : ""}`}
              onClick={() => jumpToStep(s)}
              disabled={status === "locked"}
              aria-current={isActive ? "step" : undefined}
            >
              <span className="ct-stepbar__mk">{done ? "✓" : i + 1}</span>
              <span className="ct-stepbar__label">{s.label}</span>
              {!isActive && detail && <span className="ct-stepbar__detail">{detail}</span>}
            </button>
          );
        })}
      </nav>

      <div className="wizard-step__body">{children}</div>

      <footer className="wizard-step__footer">
        <Button type="button" variant="outline" onClick={handleBack} disabled={!prevStep}>
          Back
        </Button>
        {!hideContinue && (
          <Button
            type="button"
            variant="primary"
            onClick={handleContinue}
            disabled={!canContinue}
          >
            {nextStep ? continueLabel : "Finish"}
          </Button>
        )}
      </footer>
    </section>
  );
}

export default StepShell;
