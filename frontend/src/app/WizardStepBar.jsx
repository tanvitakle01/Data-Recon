import { useNavigate } from "react-router-dom";
import { useWizard } from "../reconciliation/context/useWizard";
import { WizardActions } from "../reconciliation/context/wizardReducer";
import { getVisibleSteps } from "../reconciliation/steps/stepConfig";
import styles from "./appLayout.module.css";

// Human label for a connector kind — kept local since it's a one-line lookup.
const CONNECTOR_LABEL = {
  excel: "Excel",
  csv: "CSV",
  s4: "S/4HANA",
  ibp: "SAP IBP",
  ecc: "SAP ECC",
  bw: "SAP BW",
};

// Small, real (never fabricated) sub-label shown under a step's name — whatever
// is already confirmed for that step, or nothing yet.
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

/**
 * The wizard's 5-step progress bar, promoted out of StepShell into the app
 * header chrome so it stays visible while a long step scrolls. Behaviour is
 * unchanged from the in-card version it replaces: the same lock check, the
 * same GO_TO_STEP dispatch and the same route push.
 *
 * The active step is read from `state.step` rather than a prop, because this
 * renders in AppLayout (outside the routed step). StepRoute keeps `state.step`
 * in sync with the URL, including the dataset-preview sub-route, which reports
 * its parent source/target step.
 */
function WizardStepBar() {
  const { state, dispatch } = useWizard();
  const navigate = useNavigate();

  const steps = getVisibleSteps(state.transformationSpec?.useScriptTransformations);

  const jumpToStep = (target) => {
    if (state.stepStatus[target.key] === "locked") return;
    dispatch({ type: WizardActions.GO_TO_STEP, step: target.key });
    navigate(`/reconciliation/${target.path}`);
  };

  return (
    <div className={styles.stepbarBand}>
      <nav className={styles.stepbar} aria-label="Wizard steps">
        {steps.map((s, i) => {
          const status = state.stepStatus[s.key];
          const isActive = s.key === state.step;
          const done = status === "complete";
          const detail = stepDetail(state, s.key);
          return (
            <button
              key={s.key}
              type="button"
              className={[
                styles.step,
                isActive ? styles.stepActive : "",
                done ? styles.stepDone : "",
              ]
                .filter(Boolean)
                .join(" ")}
              onClick={() => jumpToStep(s)}
              disabled={status === "locked"}
              aria-current={isActive ? "step" : undefined}
            >
              <span className={styles.stepMk}>{done ? "✓" : i + 1}</span>
              <span className={styles.stepText}>
                <span className={styles.stepLabel}>{s.label}</span>
                {!isActive && detail && <span className={styles.stepDetail}>{detail}</span>}
              </span>
            </button>
          );
        })}
      </nav>
    </div>
  );
}

export default WizardStepBar;
