import { Button } from "@bristlecone/canopy";
import { RotateCw } from "lucide-react";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import { STAGE_ORDER, hasAllThreeInputs } from "../lib/autoRun";

// "Re-run source transformation" — the manual trigger for the unattended path.
//
// Auto-run fires by itself whenever one of the three inputs changes. This is
// the control for when nothing changed but the run should happen again anyway:
// a provider that was degraded when the chain was first compiled, a mapping
// sheet re-resolved after an edit, or simply a run the user wants rebuilt from
// scratch rather than re-executed from the approved contract (which is what
// "Re-run Reconciliation" on Results does).
//
// It replays stages 1–7 in order and lands on Results with no further click —
// unless a gate check or a transport error stops it, in which case it stops
// exactly where the automatic run would, on this step, with the failing checks
// named below.
function RerunTransformationCard() {
  const { state, dispatch } = useWizard();
  const { autoRun, transformationSpec } = state;

  // The script-transformation flow approves transformed DATA through its own
  // panel — there is no compiled chain for this pipeline to rebuild.
  if (transformationSpec.useScriptTransformations) return null;

  const running = autoRun.status === "running";
  const ready = hasAllThreeInputs(state);
  const stageIndex = STAGE_ORDER.indexOf(autoRun.stage);
  // The first pass fires on its own the moment the third input lands, so
  // calling it a "re-run" would be wrong — only a click on this button is.
  const runVerb = autoRun.trigger === "rerun" ? "Re-running" : "Running";

  const rerun = () => dispatch({ type: WizardActions.RESTART_AUTO_RUN });

  return (
    <section className="ct-card rerun-card">
      <div className="ct-card__head">
        <h3 className="ct-card__title">Source transformation</h3>
        <span className="ct-card__spacer" />
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={rerun}
          loading={running}
          disabled={running || !ready}
        >
          {running ? null : <RotateCw size={14} aria-hidden />}{" "}
          {running
            ? `${runVerb}… step ${stageIndex >= 0 ? stageIndex + 1 : 1} of ${STAGE_ORDER.length}`
            : "Re-run source transformation"}
        </Button>
      </div>
    </section>
  );
}

export default RerunTransformationCard;
