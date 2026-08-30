// Renders the payload from backend.recon_engine.service.build_simple_insights
// (see routes/insights.py's /insights/from-run-id) — a direct, honest view of
// a run's own real data (Results breakdown, quantity variance, per-mapping
// match rates, exception rows), replacing the old cockpit/executive-summary
// system for reconciliation-run insights.

const STATUS_TONE = { MATCH: "match", "QUANTITY MISMATCH": "qty", MISMATCH: "missing" };

function toneFor(status) {
  return STATUS_TONE[status] || "neutral";
}

export default function SimpleInsightsView({ payload }) {
  const { total = 0, results = [], quantityVariance, mappings = [], exceptions } = payload || {};
  const columns = exceptions?.columns || [];
  const rows = exceptions?.rows || [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <section className="ct-card">
        <div className="ct-card__head">
          <h3 className="ct-card__title">Results</h3>
        </div>
        <div className="ct-card__body">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 14 }}>
            {results.map((r) => (
              <div
                key={r.key}
                style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: 16 }}
              >
                <span className={`status-badge status-badge--${toneFor(r.status)}`}>
                  <span className="status-badge__dot" />
                  {r.label}
                </span>
                <div style={{ marginTop: 10, fontSize: 28, fontWeight: 800, color: "var(--ink)" }}>{r.count}</div>
                <div style={{ marginTop: 2, fontSize: 12.5, color: "var(--muted)" }}>{r.pct}% of {total}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {quantityVariance && (
        <section className="ct-card">
          <div className="ct-card__head">
            <h3 className="ct-card__title">Quantity Variance</h3>
          </div>
          <div className="ct-card__body" style={{ display: "flex", flexWrap: "wrap", gap: 28 }}>
            <div>
              <div style={{ fontSize: 12, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase" }}>
                Total units
              </div>
              <div style={{ marginTop: 6, fontSize: 22, fontWeight: 800, color: "var(--ink)" }}>
                {quantityVariance.totalUnits}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 12, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase" }}>
                Largest delta
              </div>
              <div style={{ marginTop: 6, fontSize: 22, fontWeight: 800, color: "var(--ink)" }}>
                {quantityVariance.largestUnit}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 12, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase" }}>
                Fields affected
              </div>
              <div style={{ marginTop: 6, fontSize: 22, fontWeight: 800, color: "var(--ink)" }}>
                {quantityVariance.fieldsAffected}
              </div>
            </div>
          </div>
        </section>
      )}

      {mappings.length > 0 && (
        <section className="ct-card">
          <div className="ct-card__head">
            <h3 className="ct-card__title">Mapping match rates</h3>
          </div>
          <div className="ct-card__body">
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 14 }}>
              {mappings.map((m) => {
                const denom = m.matched + m.unmatched;
                const pct = denom ? Math.round((m.matched / denom) * 100) : 0;
                return (
                  <div
                    key={m.label}
                    style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: 14 }}
                  >
                    <div style={{ fontWeight: 700, fontSize: 13.5, color: "var(--ink)" }}>{m.label}</div>
                    <div style={{ marginTop: 8, fontSize: 12.5, color: "var(--muted)" }}>
                      {m.matched} matched · {m.unmatched} unmatched
                    </div>
                    <div
                      style={{
                        marginTop: 10,
                        height: 6,
                        borderRadius: 3,
                        background: "var(--surface-2)",
                        overflow: "hidden",
                      }}
                    >
                      <span
                        style={{ display: "block", height: "100%", width: `${pct}%`, background: "var(--match)" }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </section>
      )}

      <section className="ct-card">
        <div className="ct-card__head">
          <h3 className="ct-card__title">Exceptions</h3>
          <span className="ct-card__spacer" />
          <span style={{ color: "var(--muted)", fontSize: 12.5, fontWeight: 600 }}>
            {rows.length} row{rows.length === 1 ? "" : "s"}
          </span>
        </div>
        {!rows.length && (
          <div className="ct-card__body">
            <p className="wizard-field__help" style={{ margin: 0 }}>
              No exceptions — every record matched.
            </p>
          </div>
        )}
        {rows.length > 0 && (
          <div className="ct-table-wrap">
            <table className="ct-table">
              <thead>
                <tr>
                  {columns.map((c) => (
                    <th key={c}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((rec, i) => (
                  <tr key={i}>
                    {columns.map((c) =>
                      c === "Status" ? (
                        <td key={c}>
                          <span className={`status-badge status-badge--${toneFor(rec[c])}`}>{rec[c]}</span>
                        </td>
                      ) : (
                        <td key={c}>{rec[c] === null || rec[c] === undefined ? "—" : String(rec[c])}</td>
                      ),
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
