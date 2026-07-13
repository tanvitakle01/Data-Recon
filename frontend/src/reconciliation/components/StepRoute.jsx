import { useEffect } from "react";
import { Navigate } from "react-router-dom";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import { getStepByKey } from "../steps/stepConfig";

// Guards direct/back-button navigation to a step whose prerequisites aren't
// met yet, and otherwise keeps state.step in sync with the URL so the
// stepper highlights the step actually being viewed.
function StepRoute({ stepKey, children }) {
  const { state, dispatch } = useWizard();
  const status = state.stepStatus[stepKey];

  useEffect(() => {
    if (status !== "locked" && state.step !== stepKey) {
      dispatch({ type: WizardActions.GO_TO_STEP, step: stepKey });
    }
  }, [stepKey, status, state.step, dispatch]);

  if (status === "locked") {
    const fallback = getStepByKey(state.step);
    return <Navigate to={`/reconciliation/${fallback?.path ?? "source"}`} replace />;
  }

  return children;
}

export default StepRoute;
