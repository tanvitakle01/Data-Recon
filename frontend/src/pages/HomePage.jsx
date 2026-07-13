import { useMemo } from "react";
import Counter from "../components/Counter";

const ACCENT_CLASS = ["accent-bar-mist", "accent-bar-sage", "accent-bar-lav", "accent-bar-peach"];

function HomePage() {
  const cards = useMemo(
    () => [
      { title: "Total Reconciliations", value: 245 },
      { title: "Total Reports Generated", value: 128 },
      { title: "Reconciliation Accuracy", display: "98.4%" },
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

  const quickActions = [
    { href: "/reconciliation", label: "Run Reconciliation", accent: "accent-bar-mist", color: "#1d4ed8" },
    { href: "/insights", label: "Analyze Comparison Report", accent: "accent-bar-sage", color: "#047857" },
    { href: "/insights/history", label: "View Historical Reports", accent: "accent-bar-lav", color: "#4338ca" },
  ];

  return (
    <div>
      <div style={{ marginBottom: 18 }}>
        <h2 style={{ margin: 0, fontWeight: 850, letterSpacing: "-0.02em" }}>
          Executive Dashboard
        </h2>
        <div style={{ color: "#64748b", marginTop: 6, fontWeight: 600 }}>
          Reconciliation & analytics overview
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3.5">
        {cards.map((c, idx) => (
          <div key={c.title} className={`surface-elevated accent-bar ${ACCENT_CLASS[idx]} p-4`}>
            <div style={{ color: "#64748b", fontSize: 12, fontWeight: 700 }}>{c.title}</div>
            <div className="mt-2.5">
              {c.value !== undefined ? (
                <Counter value={c.value} fontSize={26} fontWeight={800} textColor="#0F172A" gap={0} />
              ) : (
                <span style={{ fontSize: 26, fontWeight: 800, color: "#0F172A" }}>{c.display}</span>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1.2fr_0.8fr] gap-3.5 mt-3.5">
        <div className="surface-elevated p-4">
          <div style={{ fontWeight: 850, marginBottom: 10 }}>Recent Activity</div>
          <div style={{ color: "#64748b", fontSize: 13, fontWeight: 600, marginBottom: 10 }}>
            Latest reconciliation runs
          </div>
          <div style={{ overflowX: "auto" }}>
            <table className="table-elevated">
              <thead>
                <tr>
                  {["Reconciliation", "Status", "Timestamp"].map((h) => (
                    <th key={h}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {recent.map((r) => (
                  <tr key={r.source}>
                    <td style={{ fontWeight: 700 }}>{r.source}</td>
                    <td style={{ color: "#059669", fontWeight: 800 }}>{r.status}</td>
                    <td style={{ color: "#64748b", fontWeight: 600 }}>{r.ts}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="surface-elevated p-4">
          <div style={{ fontWeight: 850, marginBottom: 10 }}>Quick Actions</div>
          <div className="flex flex-col gap-2.5 mt-2.5">
            {quickActions.map((action) => (
              <a
                key={action.href}
                href={action.href}
                className={`accent-bar ${action.accent} hover:translate-x-0.5`}
                style={{
                  textDecoration: "none",
                  padding: "11px 14px",
                  borderRadius: 14,
                  border: "1px solid rgba(148,163,184,0.25)",
                  background: "rgba(255,255,255,0.7)",
                  color: action.color,
                  fontWeight: 900,
                  transition: "transform 160ms ease, background 160ms ease",
                }}
              >
                {action.label}
              </a>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default HomePage;
