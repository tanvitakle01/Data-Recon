import { useMemo } from "react";

function HomePage() {
  const cards = useMemo(
    () => [
      { title: "Total Reconciliations", value: 245 },
      { title: "Total Reports Generated", value: 128 },
      { title: "Reconciliation Accuracy", value: "98.4%" },
      { title: "Open Issues", value: 43 },
    ],
    [],
  );

  const recent = useMemo(
    () => [
      { source: "SAP vs SQL", status: "Completed", ts: "Today 10:35 AM" },
      { source: "SAP vs Excel", status: "Completed", ts: "Yesterday" },
    ],
    [],
  );

  return (
    <div style={{ width: "100%", margin: 0 }}>
      <div style={{ marginBottom: 18 }}>
        <h2 style={{ margin: 0, fontWeight: 850, letterSpacing: "-0.02em" }}>
          Executive Dashboard
        </h2>
        <div style={{ color: "#64748b", marginTop: 6, fontWeight: 600 }}>
          Reconciliation & analytics overview
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
          gap: 14,
        }}
        className="home-kpi-grid"
      >
        {cards.map((c) => (
          <div
            key={c.title}
            style={{
              background: "rgba(255,255,255,0.8)",
              border: "1px solid rgba(148,163,184,0.25)",
              borderRadius: 18,
              padding: 16,
              boxShadow: "0 10px 30px rgba(2,6,23,0.06)",
            }}
          >
            <div style={{ color: "#64748b", fontSize: 12, fontWeight: 700 }}>{c.title}</div>
            <div style={{ marginTop: 10, fontSize: 22, fontWeight: 900 }}>{c.value}</div>
          </div>
        ))}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1.2fr 0.8fr",
          gap: 14,
          marginTop: 14,
        }}
        className="home-bottom-grid"
      >
        <div
          style={{
            background: "rgba(255,255,255,0.8)",
            border: "1px solid rgba(148,163,184,0.25)",
            borderRadius: 18,
            padding: 16,
          }}
        >
          <div style={{ fontWeight: 850, marginBottom: 10 }}>Recent Activity</div>
          <div style={{ color: "#64748b", fontSize: 13, fontWeight: 600, marginBottom: 10 }}>
            Latest reconciliation runs
          </div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  {[
                    "Reconciliation",
                    "Status",
                    "Timestamp",
                  ].map((h) => (
                    <th
                      key={h}
                      style={{
                        textAlign: "left",
                        padding: "10px 8px",
                        borderBottom: "1px solid rgba(148,163,184,0.25)",
                        color: "#475569",
                        fontSize: 12,
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {recent.map((r) => (
                  <tr key={r.source}>
                    <td style={{ padding: "12px 8px", fontWeight: 700 }}>{r.source}</td>
                    <td style={{ padding: "12px 8px", color: "#059669", fontWeight: 800 }}>
                      {r.status}
                    </td>
                    <td style={{ padding: "12px 8px", color: "#64748b", fontWeight: 600 }}>{r.ts}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div
          style={{
            background: "rgba(255,255,255,0.8)",
            border: "1px solid rgba(148,163,184,0.25)",
            borderRadius: 18,
            padding: 16,
          }}
        >
          <div style={{ fontWeight: 850, marginBottom: 10 }}>Quick Actions</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 10 }}>
            <a
              href="/reconciliation"

              style={{
                textDecoration: "none",
                padding: "11px 14px",
                borderRadius: 14,
                border: "1px solid rgba(59,130,246,0.35)",
                background: "rgba(59,130,246,0.10)",
                color: "#1d4ed8",
                fontWeight: 900,
              }}
            >
              Run Reconciliation
            </a>
            <a
              href="/insights"
              style={{
                textDecoration: "none",
                padding: "11px 14px",
                borderRadius: 14,
                border: "1px solid rgba(16,185,129,0.35)",
                background: "rgba(16,185,129,0.10)",
                color: "#047857",
                fontWeight: 900,
              }}
            >
              Analyze Comparison Report
            </a>
            <a
              href="/insights/history"
              style={{
                textDecoration: "none",
                padding: "11px 14px",
                borderRadius: 14,
                border: "1px solid rgba(148,163,184,0.35)",
                background: "rgba(148,163,184,0.10)",
                color: "#334155",
                fontWeight: 900,
              }}
            >
              View Historical Reports
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

export default HomePage;

