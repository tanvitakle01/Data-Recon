// Shared structured rendering for one reconciliation detail row's field
// differences — used by both ContractRunResults (a completed contract run's
// Exceptions tab) and StoredRunsPage (an Auto-mode run's partial/completed
// batch preview) so the two surfaces render diffs identically instead of
// each inventing their own. See ./reconRowClassification for the paired
// classification -> Badge variant map.
export function FieldDiffs({ diffs }) {
  if (!diffs?.length) return null;
  return (
    <div className="field-diffs">
      {diffs.map((d) => (
        <span key={d.field} className="field-diff-chip">
          <strong>{d.field}</strong>: {String(d.source_value)} → {String(d.target_value)}
          {d.delta != null && ` (Δ ${d.delta}${d.variance_pct != null ? `, ${d.variance_pct}%` : ""})`}
        </span>
      ))}
    </div>
  );
}
