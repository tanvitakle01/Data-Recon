import { useWizard } from "../context/useWizard";
import { STAGE_ORDER } from "../lib/autoRun";

// What the user sees while auto-run works, and immediately after it stops.
// Rendered above the routed step so progress stays visible across the
// navigation auto-run performs itself.
const STAGE_LABELS = {
  mapping: "Reading the field mapping…",
  resolve: "Compiling the mapping sheet into transformation steps…",
  snapshots: "Snapshotting source and target…",
  validate: "Validating the transformation chain…",
  gate: "Checking every step against the full dataset…",
  approve: "Approving…",
  run: "Reconciling…",
};


function AutoRunBanner() {
  const { state } = useWizard();
  const { autoRun } = state;

  if (autoRun.status === "running") {
    const index = STAGE_ORDER.indexOf(autoRun.stage);
    return (
      <section className="autorun autorun--running" aria-live="polite">
        <div className="autorun__head">
          <span className="autorun__spinner" aria-hidden="true" />
          <div>
            <p className="autorun__title">
              {autoRun.trigger === "rerun" ? "Re-running automatically" : "Running automatically"}
            </p>
            <p className="autorun__detail">
              {STAGE_LABELS[autoRun.stage] ?? "Starting…"}
              {index >= 0 ? ` · step ${index + 1} of ${STAGE_ORDER.length}` : ""}
            </p>
          </div>
        </div>
      </section>
    );
  }

  if (autoRun.status === "error") {
    return (
      <section className="autorun autorun--error" aria-live="polite">
        <div className="autorun__head">
          <div>
            <p className="autorun__title">Auto-run stopped</p>
            <p className="autorun__detail">{autoRun.error}</p>
            <p className="autorun__detail">
              Review the mapping below and approve manually to continue.
            </p>
          </div>
        </div>
      </section>
    );
  }

  if (autoRun.status === "blocked") {
    return (
      <section className="autorun autorun--blocked" aria-live="polite">
        <div className="autorun__head">
          <div>
            <p className="autorun__title">
              Stopped before approval — {autoRun.failures.length} check
              {autoRun.failures.length === 1 ? "" : "s"} did not pass
            </p>
            <p className="autorun__detail">
              Nothing was approved or run: an uncertain chain is never approved automatically.
              The compiled steps are kept as a working draft — fix what is listed, then approve
              manually.
            </p>
          </div>
        </div>
      </section>
    );
  }

  return null;
}

// The per-check breakdown, one card per failing check. Rendered on the Mapping
// step only — that is where every one of these is fixed. One card per check
// rather than a list inside one panel, so a check reads as its own item of work.
export function AutoRunFailures() {
  const { state } = useWizard();
  const { autoRun } = state;
  if (autoRun.status !== "blocked" || autoRun.failures.length === 0) return null;

  return (
    <>
      {autoRun.failures.map((f, idx) => (
        <section className="autorun-check" key={`${f.check}-${idx}`}>
          <p className="autorun-check__name">{f.label}</p>
          <p className="autorun-check__detail">{f.detail}</p>
        </section>
      ))}
    </>
  );
}

export default AutoRunBanner;
