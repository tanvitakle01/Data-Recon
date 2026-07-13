import { useMemo } from "react";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import StepShell from "../components/StepShell";

// Only Sales Order History is offered for now. Additional comparison types
// will be added here (or sourced from /api/comparison-types) as their
// transformation logic is built out.
const COMPARISON_TYPES = [{ id: "salesorderhistory", label: "Sales Order History" }];

function ComparisonTypeStep() {
  const { state, dispatch } = useWizard();
  const selectedId = state.comparisonType?.id ?? "";

  const handleChange = (event) => {
    const id = event.target.value;
    if (!id) {
      dispatch({ type: WizardActions.SET_COMPARISON_TYPE, comparisonType: null });
      return;
    }
    const option = COMPARISON_TYPES.find((c) => c.id === id);
    dispatch({
      type: WizardActions.SET_COMPARISON_TYPE,
      comparisonType: { id: option.id, label: option.label },
    });
  };

  const canContinue = useMemo(() => Boolean(state.comparisonType), [state.comparisonType]);

  return (
    <StepShell stepKey="comparisonType" canContinue={canContinue}>
      <div className="wizard-field">
        <label className="wizard-field__label" htmlFor="comparison-type-select">
          Comparison Type
        </label>
        <select
          id="comparison-type-select"
          className="wizard-select"
          value={selectedId}
          onChange={handleChange}
        >
          <option value="">Select a comparison type…</option>
          {COMPARISON_TYPES.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
        <p className="wizard-field__help">
          This selection is carried forward and will drive the transformation rules used for
          reconciliation.
        </p>
      </div>

      {state.comparisonType && (
        <div className="wizard-dataset-summary">
          <span className="wizard-pill wizard-pill--complete">Selected</span>
          <span>{state.comparisonType.label}</span>
        </div>
      )}
    </StepShell>
  );
}

export default ComparisonTypeStep;
