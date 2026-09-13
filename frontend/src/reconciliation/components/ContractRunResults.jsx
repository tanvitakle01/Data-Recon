// Results view for contract-driven runs (the recon_engine runtime path):
// the classification summary produced by Shadow_Source vs Raw_Target, and
// next-step actions.
import { getComparisonUrl } from "../lib/reconRun";
import ShortId from "../../components/ShortId";
import { Button } from "@bristlecone/canopy";

// Outcome -> Canopy semantic color (matches the Badge outcome language:
// match=success/green, quantity_mismatch=error/red). A business key present
// on only one side is split by which side: missing_in_target (source-only)
// vs extra_in_target (target-only).
const CLASS_LABELS = [
  { key: "match", label: "Matches", color: "var(--bcone-green)" },
  { key: "quantity_mismatch", label: "Qty Mismatches", color: "var(--bcone-red)" },
  { key: "missing_in_target", label: "Missing in Target", color: "var(--bcone-orange)" },
  { key: "extra_in_target", label: "Extra in Target", color: "var(--bcone-cyan)" },
];

function ContractRunResults({ result }) {
  const summary = result?.summary ?? {};
  const run = result?.run ?? {};
  const runId = result?.run_id ?? run.run_id;

  const downloadComparison = () => {
    if (!runId) return;
    window.open(getComparisonUrl(runId), "_blank");
  };

  const total = summary.total ?? 0;
  const pct = (n) => (total ? Math.round((n / total) * 100) : 0);

  return (
    <div className="ct-col">
      {/* Post-run actions — outcomes and next steps first (business users). */}
      <div className="contract-actions results-actions">
        <ShortId value={runId} prefix="Run " />
        <Button type="button" variant="outline" onClick={downloadComparison} disabled={!runId}>
          Download Comparison Sheet
        </Button>
      </div>

      {/* KPI band: real summary counts + a proportional outcome bar. */}
      <div className="ct-kpi-band">
        <div className="ct-kpi-band__grid">
          <div className="ct-kpi-band__cell">
            <p className="ct-kpi-card__label">Records compared</p>
            <div className="ct-kpi-card__row">
              <span className="ct-kpi-band__value">{total}</span>
            </div>
            <p className="ct-kpi-band__note">Business keys present on either side</p>
          </div>
          {CLASS_LABELS.map(({ key, label, color }) => (
            <div className="ct-kpi-band__cell" key={key}>
              <p className="ct-kpi-card__label">{label}</p>
              <div className="ct-kpi-card__row">
                <span className="ct-kpi-band__value" style={{ color }}>
                  {summary[key] ?? 0}
                </span>
                <span className="ct-kpi-card__sub">{pct(summary[key] ?? 0)}%</span>
              </div>
            </div>
          ))}
        </div>
        {total > 0 && (
          <div className="ct-kpi-band__bar">
            <span style={{ width: `${pct(summary.match)}%`, background: "var(--bcone-green)" }} />
            <span
              style={{ width: `${pct(summary.quantity_mismatch)}%`, background: "var(--bcone-red)" }}
            />
            <span
              style={{ width: `${pct(summary.missing_in_target)}%`, background: "var(--bcone-orange)" }}
            />
            <span
              style={{ width: `${pct(summary.extra_in_target)}%`, background: "var(--bcone-cyan)" }}
            />
          </div>
        )}
      </div>
      <p className="wizard-field__help" style={{ marginTop: 0 }}>
        Matches include tolerance matches — fields compared with a tolerance count as a match when
        within the allowed difference.
      </p>
    </div>
  );
}

export default ContractRunResults;
