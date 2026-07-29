// Read-only pre-run date-overlap diagnostic for the contract/script wizard
// paths. Unlike the legacy DateAlignmentSummary this never claims the run is
// "blocked" — the V2 engine reconciles the full snapshots regardless; this is
// purely informational (spec Step 7: analyse overlap before reconciliation).
import { Alert } from "@bristlecone/canopy";

function Row({ label, value, tone }) {
  return (
    <div className="date-diag__row">
      <span className="date-diag__label">{label}</span>
      <span className={`date-diag__value${tone ? ` date-diag__value--${tone}` : ""}`}>{value}</span>
    </div>
  );
}

function fmtRange(range) {
  return range ? `${range.start} → ${range.end}` : "—";
}

export default function DateAlignmentDiagnostic({ alignment }) {
  if (!alignment) return null;

  const {
    source_date_column,
    target_date_column,
    source_range,
    target_range,
    overlap,
    has_overlap,
    overlap_pct,
    source_included,
    source_excluded,
    target_included,
    target_excluded,
  } = alignment;

  const noDateColumn = !source_date_column || !target_date_column;

  return (
    <div className="surface-elevated date-diag">
      <h4 className="date-diag__title">Date Alignment Analysis</h4>

      {noDateColumn ? (
        <Alert variant="info" style={{ marginTop: 8 }}>
          No date column detected on{" "}
          {!source_date_column && !target_date_column
            ? "either side"
            : !source_date_column
              ? "the source"
              : "the target"}
          . Reconciliation runs on the full dataset.
        </Alert>
      ) : (
        <>
          <Row label="Source date range" value={fmtRange(source_range)} />
          <Row label="Target date range" value={fmtRange(target_range)} />
          <Row label="Overlap window" value={fmtRange(overlap)} tone={has_overlap ? "ok" : "warn"} />
          <Row
            label="Overlap"
            value={`${overlap_pct ?? 0}% of source rows`}
            tone={has_overlap ? "ok" : "warn"}
          />
          <Row
            label="Source rows in overlap"
            value={`${source_included} in · ${source_excluded} out`}
          />
          <Row
            label="Target rows in overlap"
            value={`${target_included} in · ${target_excluded} out`}
          />
          {!has_overlap && (
            <Alert variant="warning" style={{ marginTop: 8 }}>
              Source and target date ranges do not overlap — expect a high volume of
              missing-record exceptions.
            </Alert>
          )}
        </>
      )}
    </div>
  );
}
