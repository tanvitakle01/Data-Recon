import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";
import { hasAllThreeInputs, inputSignature, runAutoPipeline } from "../lib/autoRun";

// Drives auto-run mode. Mounted once, above the routed step, so it keeps
// running while the user navigates — and so it can fire from whichever step the
// third input happened to land on.
//
// It arms on one condition: all three slots (mapping sheet, source, target) are
// populated and the current input signature has not been run yet. Because the
// reducer resets `autoRun` to idle whenever a slot is replaced, that single
// condition covers both the fresh-upload case and the mid-session replacement
// case — a replacement produces a new signature against an idle auto-run, which
// restarts the full happy path with no user click.
//
// It stays out of the way when a person has taken ownership: `humanOwned` (set
// by "Edit transformation rules" on Results) suppresses it for the rest of the
// run, and only replacing an input clears that.
export function useAutoRun() {
  const { state, dispatch } = useWizard();
  const navigate = useNavigate();
  // The signature whose pipeline is currently in flight. Guards against a
  // second pipeline starting from a re-render while the first still runs — the
  // dispatches the pipeline makes along the way re-enter this effect long
  // before it finishes.
  //
  // Deliberately NOT an effect-cleanup "cancelled" flag: this effect's very
  // first action is to dispatch `status: "running"`, which changes its own
  // dependencies and so would immediately run that cleanup and cancel the
  // pipeline it had just started.
  const inFlightRef = useRef(null);
  // Unmount is the only thing that should actually stop the result landing.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const { autoRun, transformationSpec } = state;
  const signature = inputSignature(state);
  const ready = hasAllThreeInputs(state);

  useEffect(() => {
    if (!ready || !signature) return;
    // The script-transformation flow approves transformed DATA through its own
    // panel; it has no compiled chain for this gate to reason about.
    if (transformationSpec.useScriptTransformations) return;
    if (transformationSpec.humanOwned) return;
    if (inFlightRef.current === signature) return;
    // Already settled for exactly these inputs — done, blocked, or errored.
    if (autoRun.status !== "idle" && autoRun.signature === signature) return;

    inFlightRef.current = signature;

    // `trigger` is carried over, not set: RESTART_AUTO_RUN already marked this
    // pass a "rerun" before the hook saw it, and every other entry point resets
    // to the idle default ("auto"). Overwriting it here would make a clicked
    // re-run indistinguishable from the unattended first pass.
    dispatch({
      type: WizardActions.SET_AUTO_RUN,
      autoRun: {
        status: "running",
        stage: "mapping",
        trigger: autoRun.trigger,
        failures: [],
        error: null,
        signature,
      },
    });

    runAutoPipeline({
      state,
      dispatch,
      onStage: (stage) => {
        if (mountedRef.current) dispatch({ type: WizardActions.SET_AUTO_RUN, autoRun: { stage } });
      },
    })
      .then((outcome) => {
        if (!mountedRef.current) return;
        if (outcome.outcome === "reconciled") {
          dispatch({
            type: WizardActions.SET_AUTO_RUN,
            autoRun: { status: "done", stage: null, failures: [], error: null, signature },
          });
          // Zero clicks after the third upload: land the user on Results.
          navigate("/reconciliation/reconciliation");
          return;
        }
        // Blocked: stop at the failing stage, keep the compiled work as the
        // working draft, and send the user to the Mapping step where the named
        // failures are shown and manual approval lives.
        dispatch({
          type: WizardActions.SET_AUTO_RUN,
          autoRun: {
            status: "blocked",
            stage: outcome.stage,
            failures: outcome.failures,
            error: null,
            signature,
          },
        });
        navigate("/reconciliation/transformation-spec");
      })
      .catch((err) => {
        if (!mountedRef.current) return;
        const detail = err?.response?.data?.detail;
        dispatch({
          type: WizardActions.SET_AUTO_RUN,
          autoRun: {
            status: "error",
            stage: null,
            failures: [],
            error:
              typeof detail === "string"
                ? detail
                : detail?.message || err?.message || "Auto-run failed.",
            signature,
          },
        });
        navigate("/reconciliation/transformation-spec");
      })
      .finally(() => {
        if (inFlightRef.current === signature) inFlightRef.current = null;
      });

    // `state` is deliberately not a dependency: the pipeline dispatches into it
    // as it runs, and re-running this effect on every one of those updates
    // would restart the pipeline mid-flight. The signature covers every input
    // change that should re-arm it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    ready,
    signature,
    autoRun.status,
    autoRun.signature,
    transformationSpec.humanOwned,
    transformationSpec.useScriptTransformations,
    dispatch,
    navigate,
  ]);

  return autoRun;
}

export default useAutoRun;
