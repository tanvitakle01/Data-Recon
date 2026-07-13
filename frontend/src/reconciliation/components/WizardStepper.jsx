import { useNavigate } from "react-router-dom";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import { getVisibleSteps } from "../steps/stepConfig";

function WizardStepper() {
  const { state, dispatch } = useWizard();
  const navigate = useNavigate();

  const steps = getVisibleSteps(state.transformationSpec?.useScriptTransformations);

  const handleJump = (step) => {
    if (state.stepStatus[step.key] === "locked") return;
    dispatch({ type: WizardActions.GO_TO_STEP, step: step.key });
    navigate(`/reconciliation/${step.path}`);
  };

  return (
    <nav className="wizard-stepper" aria-label="Reconciliation wizard steps">
      <ol>
        {steps.map((step, idx) => {
          const status = state.stepStatus[step.key];
          const isActive = state.step === step.key;
          return (
            <li key={step.key} className={`wizard-stepper__item is-${status} ${isActive ? "is-active" : ""}`}>
              <button
                type="button"
                onClick={() => handleJump(step)}
                disabled={status === "locked"}
                aria-current={isActive ? "step" : undefined}
              >
                <span className="wizard-stepper__num">{status === "complete" ? "✓" : idx + 1}</span>
                <span className="wizard-stepper__label">{step.label}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export default WizardStepper;
