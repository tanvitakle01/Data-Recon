// Results view for contract-driven runs (the recon_engine runtime path):
// the classification summary produced by Shadow_Source vs Raw_Target,
// plus next-step actions. Purely presentational.
import { useNavigate } from "react-router-dom";
import { getComparisonUrl } from "../lib/reconRun";

const CLASS_LABELS = [
  { key: "match", label: "Matches", tone: "ok" },
  { key: "mismatch", label: "Qty Mismatches", tone: "fail" },
  { key: "missing_in_source", label: "Missing in Source", tone: "warn" },
  { key: "missing_in_target", label: "Missing in Target", tone: "warn" },
];

function ContractRunResults({ result }) {
  const navigate = useNavigate();
  const summary = result?.summary ?? {};
  const run = result?.run ?? {};
  const runId = result?.run_id ?? run.run_id;

  const downloadComparison = () => {
    if (!runId) return;
    window.open(getComparisonUrl(runId), "_blank");
  };

  return (
    <div className="contract-run-results">
      {/* Post-run actions — outcomes and next steps first (business users). */}
      <div className="contract-actions results-actions">
        <button
          type="button"
          className="wizard-btn wizard-btn--primary"
          onClick={() => runId && navigate(`/insights/run/${runId}`)}
          disabled={!runId}
        >
          View Insights
        </button>
        <button
          type="button"
          className="wizard-btn wizard-btn--ghost"
          onClick={downloadComparison}
          disabled={!runId}
        >
          Download Comparison Sheet
        </button>
      </div>

      {/* Classification summary */}
      <div className="class-cards">
        {CLASS_LABELS.map(({ key, label, tone }) => (
          <div key={key} className={`class-card class-card--${tone}`}>
            <p className="class-card__value">{summary[key] ?? 0}</p>
            <p className="class-card__label">{label}</p>
          </div>
        ))}
        <div className="class-card class-card--total">
          <p className="class-card__value">{summary.total ?? 0}</p>
          <p className="class-card__label">Total Records</p>
        </div>
      </div>
      <p className="wizard-field__help">
        Matches include tolerance matches — fields compared with a tolerance count as a match when
        within the allowed difference.
      </p>

    </div>
  );
}

export default ContractRunResults;
