import { useNavigate } from "react-router-dom";
import { Button } from "@bristlecone/canopy";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import { getVisibleSteps } from "../steps/stepConfig";

// The horizontal step bar this card used to render now lives in the app header
// chrome (app/WizardStepBar.jsx) so it stays visible while a long step scrolls.

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

  const handleBack = () => {
    if (prevStep) goToStep(prevStep);
  };

  const handleContinue = () => {
    dispatch({ type: WizardActions.COMPLETE_STEP, step: stepKey });
    if (nextStep) goToStep(nextStep);
  };

  // Discards all in-memory wizard progress and returns to Step 1. Confirmed
  // first since this can't be undone.
  const handleStartOver = () => {
    if (!window.confirm("Start over? This discards all progress in this wizard.")) return;
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
