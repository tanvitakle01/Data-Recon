import { useNavigate } from "react-router-dom";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import { getVisibleSteps } from "../steps/stepConfig";

function StepShell({ stepKey, children, canContinue = true, continueLabel = "Continue" }) {
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

  return (
    <section className="wizard-step">
      <header className="wizard-step__header">
        <p className="wizard-step__eyebrow">
          Step {index + 1} of {steps.length}
        </p>
        <h2 className="wizard-step__title">{step?.label}</h2>
        <p className="wizard-step__desc">{step?.description}</p>
      </header>

      <div className="wizard-step__body">{children}</div>

      <footer className="wizard-step__footer">
        <button type="button" className="wizard-btn wizard-btn--ghost" onClick={handleBack} disabled={!prevStep}>
          Back
        </button>
        <button
          type="button"
          className="wizard-btn wizard-btn--primary"
          onClick={handleContinue}
          disabled={!canContinue}
        >
          {nextStep ? continueLabel : "Finish"}
        </button>
      </footer>
    </section>
  );
}

export default StepShell;
