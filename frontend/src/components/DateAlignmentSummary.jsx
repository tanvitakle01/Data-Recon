function RangeRow({ label, range }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0" }}>
      <span style={{ color: "#64748b", fontSize: 13, fontWeight: 600 }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 800, color: "#0f172a" }}>
        {range ? `${range.start} → ${range.end}` : "No dates detected"}
      </span>
    </div>
  );
}

function CountPill({ label, included, excluded }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 2,
        padding: "10px 14px",
        borderRadius: 12,
        background: "rgba(148,163,184,0.10)",
        minWidth: 140,
      }}
    >
      <span style={{ fontSize: 12, fontWeight: 700, color: "#64748b" }}>{label}</span>
      <span style={{ fontSize: 14, fontWeight: 800, color: "#047857" }}>{included} included</span>
      <span style={{ fontSize: 12, fontWeight: 700, color: excluded > 0 ? "#b91c1c" : "#94a3b8" }}>
        {excluded} excluded
      </span>
    </div>
  );
}

function DateAlignmentSummary({ alignment, onOverride, overriding }) {
  if (!alignment) return null;

  const {
    source_date_column,
    target_date_column,
    source_range,
    target_range,
    overlap,
    has_overlap,
    source_included,
    source_excluded,
    target_included,
    target_excluded,
  } = alignment;

  const dateColumnMissing = !source_date_column || !target_date_column;

  return (
    <div
      className="surface-elevated"
      style={{ marginTop: 16, marginBottom: 16, padding: 16 }}
    >
      <h4 style={{ margin: "0 0 10px 0" }}>Date Alignment Summary</h4>

      {dateColumnMissing ? (
        <div style={{ color: "#92400e", fontSize: 13, marginBottom: 8 }}>
          ℹ️ Could not detect a date column on {!source_date_column && !target_date_column
            ? "either side"
            : !source_date_column
              ? "the S/4 side"
              : "the IBP side"}
          . Date alignment was skipped — reconciliation will run on the full dataset.
        </div>
      ) : (
        <>
          <RangeRow label="S/4 date range" range={source_range} />
          <RangeRow label="IBP date range" range={target_range} />
          <RangeRow label="Overlap window" range={overlap} />

          {!has_overlap ? (
            <div
              style={{
                marginTop: 10,
                padding: "10px 12px",
                borderRadius: 10,
                background: "rgba(220,38,38,0.08)",
                color: "#b91c1c",
                fontSize: 13,
                fontWeight: 700,
              }}
            >
              ⚠️ No overlapping period between S/4 and IBP — reconciliation is blocked until you
              override.
              {onOverride && (
                <div style={{ marginTop: 8 }}>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={onOverride}
                    disabled={overriding}
                  >
                    {overriding ? "Reconciling…" : "Override & Reconcile Anyway"}
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div style={{ display: "flex", gap: 12, marginTop: 10, flexWrap: "wrap" }}>
              <CountPill label="S/4 records" included={source_included} excluded={source_excluded} />
              <CountPill label="IBP records" included={target_included} excluded={target_excluded} />
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default DateAlignmentSummary;
