// Results view for contract-driven runs (the recon_engine runtime path):
// the classification summary produced by Shadow_Source vs Raw_Target,
// plus next-step actions. Purely presentational.
import { useNavigate } from "react-router-dom";
import { getComparisonUrl } from "../lib/reconRun";
import { Button, Card } from "@bristlecone/canopy";

// Outcome -> Canopy semantic color (matches the Badge outcome language:
// match=success/green, mismatch=error/red, missing=warning/orange,
// extra=info/blue). "Missing in Source" = row only in target = extra;
// "Missing in Target" = a true miss. Total is neutral charcoal.
const CLASS_LABELS = [
  { key: "match", label: "Matches", color: "var(--bcone-green)" },
  { key: "mismatch", label: "Qty Mismatches", color: "var(--bcone-red)" },
  { key: "missing_in_source", label: "Missing in Source", color: "var(--bcone-blue)" },
  { key: "missing_in_target", label: "Missing in Target", color: "var(--bcone-orange)" },
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
        <Button
          type="button"
          variant="primary"
          onClick={() => runId && navigate(`/insights/run/${runId}`)}
          disabled={!runId}
        >
          View Insights
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={downloadComparison}
          disabled={!runId}
        >
          Download Comparison Sheet
        </Button>
      </div>

      {/* Classification summary — outcome stat tiles built from Canopy Card,
          the big number colored by the Canopy outcome hue. */}
      <div className="class-cards">
        {CLASS_LABELS.map(({ key, label, color }) => (
          <Card key={key} padded={false} className="p-4 text-center">
            <p className="text-3xl font-black leading-none" style={{ color }}>
              {summary[key] ?? 0}
            </p>
            <p className="mt-1 text-sm font-bold text-[var(--bcone-gray)]">{label}</p>
          </Card>
        ))}
        <Card padded={false} className="p-4 text-center">
          <p
            className="text-3xl font-black leading-none"
            style={{ color: "var(--bcone-charcoal)" }}
          >
            {summary.total ?? 0}
          </p>
          <p className="mt-1 text-sm font-bold text-[var(--bcone-gray)]">Total Records</p>
        </Card>
      </div>
      <p className="wizard-field__help">
        Matches include tolerance matches — fields compared with a tolerance count as a match when
        within the allowed difference.
      </p>

    </div>
  );
}

export default ContractRunResults;
