import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import api from "../services/api";
import {
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  LineChart,
  Line,
  CartesianGrid,
} from "recharts";
import OperationalIntelligenceCenter from "../components/insights/OperationalIntelligenceCenter";



function useQuery() {
  const { search } = useLocation();
  return useMemo(() => new URLSearchParams(search), [search]);
}


function SeverityPill({ severity }) {
  const s = String(severity ?? "Low").toLowerCase();
  const cfg =
    s === "high"
      ? { bg: "rgba(239,68,68,0.12)", border: "rgba(239,68,68,0.35)", text: "#b91c1c" }
      : s === "medium"
        ? { bg: "rgba(245,158,11,0.12)", border: "rgba(245,158,11,0.35)", text: "#a16207" }
        : { bg: "rgba(16,185,129,0.10)", border: "rgba(16,185,129,0.32)", text: "#047857" };

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "6px 10px",
        borderRadius: 999,
        background: cfg.bg,
        border: `1px solid ${cfg.border}`,
        color: cfg.text,
        fontWeight: 900,
        fontSize: 12,
        lineHeight: 1,
      }}
    >
      {String(severity ?? "Low")}
    </span>
  );
}

function SectionCard({ title, children }) {
  return (
    <div
      style={{
        background: "rgba(255,255,255,0.8)",
        border: "1px solid rgba(148,163,184,0.25)",
        borderRadius: 18,
        padding: 16,
      }}
    >
      <div style={{ fontWeight: 900, marginBottom: 10 }}>{title}</div>
      {children}
    </div>
  );
}

function NoData({ message = "No data available" }) {
  return <div style={{ color: "#64748b", fontWeight: 700 }}>{message}</div>;
}

function OperationalIntelligencePanel({ operationalIntelligence }) {
  const patterns = operationalIntelligence?.patternIntelligence?.patterns || [];
  const exceptions = operationalIntelligence?.exceptionIntelligence?.criticalExceptions || [];
  const trends = operationalIntelligence?.trendIntelligence?.trendInsights || [];
  const comparisons = operationalIntelligence?.comparisonIntelligence?.comparisons || [];
  const paretoObj = operationalIntelligence?.paretoAnalysis || null;
  const risks = operationalIntelligence?.riskEntities || [];

  const isEmpty = (arr) => !Array.isArray(arr) || arr.length === 0;






  return (
    <div
      style={{
        marginTop: 14,
        background: "rgba(255,255,255,0.8)",
        border: "1px solid rgba(148,163,184,0.25)",
        borderRadius: 18,
        padding: 16,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline", marginBottom: 12 }}>
        <div>
          <div style={{ fontWeight: 950, fontSize: 18 }}>📊 Operational Intelligence Center</div>
          <div style={{ color: "#64748b", fontWeight: 700, fontSize: 13, marginTop: 4 }}>
            Advanced analytics visualization returned by the backend.
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <SectionCard title="1) Pattern Intelligence">
          {isEmpty(patterns) ? (
            <NoData />
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 10 }}>
              {patterns.map((p, idx) => (
                <div
                  key={idx}
                  style={{
                    background: "rgba(255,255,255,0.85)",
                    border: "1px solid rgba(148,163,184,0.18)",
                    borderRadius: 16,
                    padding: 12,
                  }}
                >
                  <div style={{ fontWeight: 950, marginBottom: 6 }}>{p?.pattern ?? p?.label ?? "Pattern"}</div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                    <div>
                      <div style={{ color: "#64748b", fontSize: 12, fontWeight: 800 }}>Frequency</div>
                      <div style={{ fontWeight: 950 }}>{p?.frequency ?? p?.freq ?? "—"}</div>
                    </div>
                    <div>
                      <div style={{ color: "#64748b", fontSize: 12, fontWeight: 800 }}>Affected Dimensions</div>
                      <div style={{ fontWeight: 950 }}>{Array.isArray(p?.affectedDimensions) ? p?.affectedDimensions?.join(", ") : p?.affectedDimensions ?? "—"}</div>
                    </div>
                  </div>
                  {p?.confidence != null && (
                    <div style={{ marginTop: 8 }}>
                      <div style={{ color: "#64748b", fontSize: 12, fontWeight: 800 }}>Confidence</div>
                      <div style={{ fontWeight: 950 }}>{p?.confidence}</div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </SectionCard>

        <SectionCard title="2) Exception & Anomaly Intelligence">
          {isEmpty(exceptions) ? (
            <NoData />
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    {[
                      "Anomaly Type",
                      "Severity",
                      "Severity Score",
                      "Impacted Entities",
                    ].map((h) => (
                      <th
                        key={h}
                        style={{
                          textAlign: "left",
                          padding: 10,
                          fontSize: 12,
                          color: "#64748b",
                          fontWeight: 900,
                          borderBottom: "1px solid rgba(148,163,184,0.25)",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {exceptions.map((e, idx) => {
                    const severity = e?.severity || e?.priority;
                    const score = e?.score ?? e?.severityScore ?? e?.risk_score ?? e?.riskScore ?? "—";
                    const entities = e?.impactedEntities ?? e?.entities ?? e?.entity ?? "—";
                    return (
                      <tr key={idx}>
                        <td style={{ padding: 10, fontWeight: 800 }}>
                          {e?.category ?? e?.anomalyType ?? e?.exceptionType ?? e?.type ?? "—"}
                        </td>
                        <td style={{ padding: 10 }}>
                          <SeverityPill severity={severity} />
                        </td>
                        <td style={{ padding: 10, fontWeight: 900 }}>{score}</td>
                        <td style={{ padding: 10, fontWeight: 800 }}>
                          {Array.isArray(entities) ? entities.join(", ") : entities}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </SectionCard>

        <SectionCard title="3) Trend Intelligence">
          {isEmpty(trends) ? (
            <NoData />
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 10 }}>
              {trends.map((t, idx) => {
                const direction = t?.direction || t?.trend;
                const growth = t?.changePct ?? t?.growth ?? t?.slope ?? t?.change ?? t?.acceleration;
                const timeRange = t?.timeRange ?? t?.time_range ?? t?.range ?? "—";
                return (
                  <div
                    key={idx}
                    style={{
                      background: "rgba(255,255,255,0.85)",
                      border: "1px solid rgba(148,163,184,0.18)",
                      borderRadius: 16,
                      padding: 12,
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center" }}>
                      <div style={{ fontWeight: 950 }}>{t?.entity ?? t?.label ?? "Trend"}</div>
                      <SeverityPill severity={String(direction).includes("Down") || String(direction).includes("Decreasing") ? "High" : "Low"} />
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 8 }}>
                      <div>
                        <div style={{ color: "#64748b", fontSize: 12, fontWeight: 800 }}>Direction</div>
                        <div style={{ fontWeight: 950 }}>{direction ?? "—"}</div>
                      </div>
                      <div>
                        <div style={{ color: "#64748b", fontSize: 12, fontWeight: 800 }}>Slope / Change %</div>
                        <div style={{ fontWeight: 950 }}>{growth ?? "—"}</div>
                      </div>
                    </div>
                    {timeRange !== "—" && (
                      <div style={{ marginTop: 8 }}>
                        <div style={{ color: "#64748b", fontSize: 12, fontWeight: 800 }}>Time range</div>
                        <div style={{ fontWeight: 950 }}>{timeRange}</div>
                      </div>
                    )}
                    <div style={{ marginTop: 10, height: 54, borderRadius: 12, background: "linear-gradient(90deg, rgba(59,130,246,0.10), rgba(16,185,129,0.10))" }} />
                  </div>
                );
              })}
            </div>
          )}
        </SectionCard>

        <SectionCard title="4) Comparison Intelligence">
          {isEmpty(comparisons) ? (
            <NoData />
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 10 }}>
              {comparisons.map((c, idx) => {
                const a = c?.entityA ?? c?.a ?? c?.left ?? "—";
                const b = c?.entityB ?? c?.b ?? c?.right ?? "—";
                const variance = c?.delta ?? c?.variance ?? c?.difference ?? c?.percentageDifference ?? c?.pctDiff ?? "—";
                const entityType = c?.entityType ?? c?.type ?? "Entity";
                return (
                  <div
                    key={idx}
                    style={{
                      background: "rgba(255,255,255,0.85)",
                      border: "1px solid rgba(148,163,184,0.18)",
                      borderRadius: 16,
                      padding: 12,
                    }}
                  >
                    <div style={{ fontWeight: 950, marginBottom: 8 }}>
                      {entityType}: {String(a)} vs {String(b)}
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
                      <div>
                        <div style={{ color: "#64748b", fontSize: 12, fontWeight: 800 }}>Entity A</div>
                        <div style={{ fontWeight: 950 }}>{a}</div>
                      </div>
                      <div>
                        <div style={{ color: "#64748b", fontSize: 12, fontWeight: 800 }}>Entity B</div>
                        <div style={{ fontWeight: 950 }}>{b}</div>
                      </div>
                      <div>
                        <div style={{ color: "#64748b", fontSize: 12, fontWeight: 800 }}>Δ / % Difference</div>
                        <div style={{ fontWeight: 950 }}>{variance}</div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </SectionCard>

        <SectionCard title="5) Pareto Analysis (80/20)">
          {paretoObj ? (
            <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 10 }}>
              {[
                { key: "plants", label: "Plants" },
                { key: "materials", label: "Materials" },
                { key: "suppliers", label: "Suppliers" },
              ].map(({ key, label }) => {
                const block = paretoObj?.[key] ?? {};
                const topContributors = block?.topContributors ?? [];
                const coverage80Percent = block?.coverage80Percent;
                return (
                  <div
                    key={key}
                    style={{
                      background: "rgba(255,255,255,0.85)",
                      border: "1px solid rgba(148,163,184,0.18)",
                      borderRadius: 16,
                      padding: 12,
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                      <div style={{ fontWeight: 950 }}>{label}</div>
                      <div style={{ color: "#64748b", fontWeight: 900, fontSize: 12 }}>
                        80% coverage items: {coverage80Percent ?? "—"}
                      </div>
                    </div>
                    {isEmpty(topContributors) ? (
                      <div style={{ marginTop: 8 }}>
                        <NoData message="No data available" />
                      </div>
                    ) : (
                      <div style={{ marginTop: 10, display: "grid", gap: 8 }}>
                        {topContributors.slice(0, 8).map((p, idx) => {
                          const share = Number(p?.share ?? 0);
                          return (
                            <div key={idx}>
                              <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                                <div style={{ fontWeight: 900 }}>{p?.entity ?? "Contributor"}</div>
                                <div style={{ color: "#64748b", fontWeight: 900 }}>{share}%</div>
                              </div>
                              <div
                                style={{
                                  marginTop: 6,
                                  height: 10,
                                  borderRadius: 999,
                                  background: "rgba(148,163,184,0.20)",
                                  overflow: "hidden",
                                }}
                              >
                                <div
                                  style={{
                                    width: `${Math.min(100, Math.max(0, share))}%`,
                                    height: "100%",
                                    background: `linear-gradient(90deg, rgba(59,130,246,0.85), rgba(16,185,129,0.85))`,
                                  }}
                                />
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <NoData />
          )}
        </SectionCard>

        <SectionCard title="6) Top Risk Entities">
          {isEmpty(risks) ? (
            <NoData />
          ) : (
            <div style={{ display: "grid", gap: 10 }}>
              {risks.slice(0, 10).map((r, idx) => {
                const name = r?.entity ?? r?.name ?? r?.item ?? r?.material ?? "—";
                const score = r?.riskScore ?? r?.risk_score ?? r?.score ?? "—";
                const factors = r?.contributingFactors ?? r?.factors ?? r?.drivers ?? [];
                const factorsStr = Array.isArray(factors) ? factors.join(", ") : factors;
                return (
                  <div
                    key={idx}
                    style={{
                      background: "rgba(255,255,255,0.85)",
                      border: "1px solid rgba(148,163,184,0.18)",
                      borderRadius: 16,
                      padding: 12,
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                      <div style={{ fontWeight: 950 }}>
                        {idx + 1}. {name}
                      </div>
                      <div style={{ fontWeight: 950, color: "#0f172a" }}>Risk: {score}</div>
                    </div>
                    {factorsStr && factorsStr !== "—" && (
                      <div style={{ marginTop: 8, color: "#475569", fontWeight: 800, fontSize: 13 }}>
                        Contributing factors: {factorsStr}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </SectionCard>

      </div>

    </div>
  );
}


function KPI({ label, value }) {
  return (
    <div
      style={{
        background: "rgba(255,255,255,0.8)",
        border: "1px solid rgba(148,163,184,0.25)",
        borderRadius: 18,
        padding: 16,
        boxShadow: "0 10px 30px rgba(2,6,23,0.06)",
      }}
    >
      <div style={{ color: "#64748b", fontSize: 12, fontWeight: 700 }}>{label}</div>
      <div style={{ marginTop: 10, fontSize: 22, fontWeight: 900 }}>{value}</div>
    </div>
  );
}

class InsightsErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error) {
    // eslint-disable-next-line no-console
    console.error("InsightsPage render crashed:", error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 16, borderRadius: 18, border: "1px solid rgba(185,28,28,0.25)", background: "rgba(239,68,68,0.06)" }}>
          <div style={{ fontWeight: 950, color: "#b91c1c", marginBottom: 6 }}>Insights failed to render</div>
          <div style={{ color: "#7f1d1d", fontWeight: 700, fontSize: 13 }}>
            {this.state.error?.message ? String(this.state.error.message) : "Unexpected render error"}
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

function InsightsPageInner() {
  const query = useQuery();
  const fileId = query.get("file_id");


  const [mode] = useState(fileId ? "fromFileId" : "upload");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const [payload, setPayload] = useState(null);

  const [uploadFile, setUploadFile] = useState(null);
  const [uploadSheetName, setUploadSheetName] = useState("");

  const aiSectionRef = useRef(null);

  useEffect(() => {
    // Derive mode from URL param; avoid setState-on-effect for lint stability.
  }, [fileId]);


  useEffect(() => {
    const runModeA = async () => {
      if (!fileId) return;
      setBusy(true);
      setError(null);
      try {
        const res = await api.post("/insights/from-file-id", { file_id: fileId });
        const data = res.data?.payload ?? null;
        console.log("INSIGHTS API RESPONSE:", data);
        setPayload(data);


        // scroll to AI insights section
        requestAnimationFrame(() => {
          if (aiSectionRef.current) {
            aiSectionRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
          }
        });
      } catch (e) {
        setError(e?.response?.data?.detail || "Failed to generate insights");
      } finally {
        setBusy(false);
      }
    };

    runModeA();
  }, [fileId]);

  const summary = payload?.summary || {};
  const kpis = payload?.kpis || [];

  const getKpi = (title) => {
    const found = kpis.find((k) => k.title === title);
    return found ? found.value : 0;
  };

  const accuracy = summary?.accuracy ?? 0;

  const onUploadGenerate = async () => {
    if (!uploadFile) return;
    setBusy(true);
    setError(null);
    setPayload(null);

    try {
      const formData = new FormData();
      formData.append("file", uploadFile);
      formData.append("sheet_name", uploadSheetName);

      // backend expects UploadFile with `file` field
      const res = await api.post("/insights", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setPayload(res.data?.payload ?? null);

      requestAnimationFrame(() => {
        if (aiSectionRef.current) {
          aiSectionRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      });
    } catch (e) {
      setError(e?.response?.data?.detail || "Insights generation failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ width: "100%", margin: 0 }}>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontWeight: 900, letterSpacing: "-0.02em" }}>Insights</h2>
        <div style={{ color: "#64748b", marginTop: 6, fontWeight: 600 }}>
          {mode === "fromFileId" ? "Auto-generated from reconciliation output" : "Standalone analysis"}
        </div>
      </div>

      {error && <div style={{ color: "#b91c1c", fontWeight: 700, marginBottom: 12 }}>⚠️ {String(error)}</div>}

      {mode === "upload" && (
        <div
          style={{
            background: "rgba(255,255,255,0.8)",
            border: "1px solid rgba(148,163,184,0.25)",
            borderRadius: 18,
            padding: 16,
            marginBottom: 14,
          }}
        >
          <div style={{ fontWeight: 850, marginBottom: 10 }}>Upload comparison report</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 240px", gap: 12, alignItems: "end" }}>
            <div>
              <label style={{ display: "block", color: "#475569", fontWeight: 800, fontSize: 13, marginBottom: 8 }}>
                Excel/CSV file
              </label>
              <input
                type="file"
                accept=".xlsx,.xls,.csv"
                onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
              />
              <div style={{ color: "#64748b", fontWeight: 600, marginTop: 6, fontSize: 12 }}>
                Supported: Excel output with a “Remarks” column.
              </div>
            </div>
            <div>
              <label style={{ display: "block", color: "#475569", fontWeight: 800, fontSize: 13, marginBottom: 8 }}>
                Sheet name (optional)
              </label>
              <input
                type="text"
                value={uploadSheetName}
                onChange={(e) => setUploadSheetName(e.target.value)}
                placeholder="Compared_Output"
                style={{ width: "100%", padding: 10, borderRadius: 12, border: "1px solid #d1d5db" }}
              />
            </div>
          </div>
          <div style={{ marginTop: 14 }}>
            <button
              type="button"
              disabled={busy || !uploadFile}
              onClick={onUploadGenerate}
              style={{
                padding: "11px 16px",
                borderRadius: 14,
                border: "1px solid #6b7280",
                background: busy || !uploadFile ? "#f3f4f6" : "#111827",
                color: busy || !uploadFile ? "#6b7280" : "white",
                cursor: busy || !uploadFile ? "not-allowed" : "pointer",
                fontWeight: 900,
              }}
            >
              {busy ? "Generating…" : "Generate Insights"}
            </button>
          </div>
        </div>
      )}

      {busy && mode === "fromFileId" && (
        <div style={{ color: "#64748b", fontWeight: 800 }}>Generating insights…</div>
      )}

      {payload && (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
              gap: 14,
              marginTop: 14,
            }}
          >
            <KPI label="Accuracy %" value={`${accuracy}%`} />
            <KPI label="Total Mismatches" value={summary.mismatchedRecords ?? 0} />
            <KPI label="Missing Records" value={getKpi("Missing in Target")} />
            <KPI label="Extra Records" value={getKpi("Extra in Target")} />
          </div>

          <div style={{ marginTop: 14, background: "rgba(255,255,255,0.8)", border: "1px solid rgba(148,163,184,0.25)", borderRadius: 18, padding: 16 }}>
            <div style={{ fontWeight: 900, marginBottom: 10 }}>Visualizations</div>


            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
              <div style={{ background: "rgba(255,255,255,0.85)", border: "1px solid rgba(148,163,184,0.18)", borderRadius: 16, padding: 14 }}>
                <div style={{ fontWeight: 850, marginBottom: 8 }}>Mismatch by Type</div>
                <div style={{ height: 260, minHeight: 260 }}>
                  <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0}>

                    <PieChart>
                      <Pie
                        data={payload?.charts?.mismatchByType ?? []}
                        dataKey="value"
                        nameKey="title"
                        cx="50%"
                        cy="50%"
                        outerRadius={90}
                        label
                      >
                        {(payload?.charts?.mismatchByType ?? []).map((entry, idx) => (
                          <Cell
                            key={`cell-type-${idx}`}
                            fill={
                              idx === 0 ? "#ef4444" : idx === 1 ? "#3b82f6" : idx === 2 ? "#f59e0b" : "#64748b"
                            }
                          />
                        ))}
                      </Pie>
                      <Tooltip />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div style={{ background: "rgba(255,255,255,0.85)", border: "1px solid rgba(148,163,184,0.18)", borderRadius: 16, padding: 14 }}>
                <div style={{ fontWeight: 850, marginBottom: 8 }}>Trend</div>
                <div style={{ height: 260 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={payload?.charts?.trend ?? []} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="period" tick={{ fontSize: 12 }} />
                      <YAxis />
                      <Tooltip />
                      <Line type="monotone" dataKey="mismatches" stroke="#111827" strokeWidth={3} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div style={{ gridColumn: "1 / span 2", background: "rgba(255,255,255,0.85)", border: "1px solid rgba(148,163,184,0.18)", borderRadius: 16, padding: 14 }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                  <div>
                    <div style={{ fontWeight: 850, marginBottom: 8 }}>Mismatch by Plant</div>
                    <div style={{ height: 240 }}>
                      <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={payload?.charts?.mismatchByPlant ?? []} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" />
                          <XAxis dataKey="plant" tick={{ fontSize: 12 }} interval={0} />
                          <YAxis />
                          <Tooltip />
                          <Bar dataKey="mismatches" fill="#3b82f6" />
                        </BarChart>

                      </ResponsiveContainer>
                    </div>
                  </div>

                  <div>
                    <div style={{ fontWeight: 850, marginBottom: 8 }}>Top Materials</div>
                    <div style={{ height: 240 }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={payload?.charts?.topMaterials ?? []} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" />
                          <XAxis dataKey="material" tick={{ fontSize: 12 }} interval={0} />
                          <YAxis />
                          <Tooltip />
                          <Bar dataKey="mismatches" fill="#f59e0b" />
                        </BarChart>

                      </ResponsiveContainer>
                    </div>
                  </div>
                </div>

                {(payload?.charts?.mismatchByPlant ?? []).length === 0 && (payload?.charts?.topMaterials ?? []).length === 0 && (payload?.charts?.trend ?? []).length === 0 && (payload?.charts?.mismatchByType ?? []).length > 0 && (
                  <div style={{ marginTop: 10, color: "#64748b", fontWeight: 650, fontSize: 13 }}>
                    Chart breakdown limited by missing columns in the uploaded reconciliation output.
                  </div>
                )}
              </div>
            </div>
          </div>


          <div
            ref={aiSectionRef}
            style={{
              marginTop: 14,
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 14,
            }}
          >
            <div
              style={{
                background: "rgba(255,255,255,0.8)",
                border: "1px solid rgba(148,163,184,0.25)",
                borderRadius: 18,
                padding: 16,
              }}
            >
              <div style={{ fontWeight: 900, marginBottom: 8 }}>AI Insights</div>
              {(payload?.insights || []).length === 0 ? (
                <div style={{ color: "#64748b", fontWeight: 700 }}>No insights generated.</div>
              ) : (
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {payload.insights.map((t, idx) => (
                    <li key={idx} style={{ marginBottom: 8, color: "#0f172a", fontWeight: 650 }}>
                      {t}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div
              style={{
                background: "rgba(255,255,255,0.8)",
                border: "1px solid rgba(148,163,184,0.25)",
                borderRadius: 18,
                padding: 16,
              }}
            >
              <div style={{ fontWeight: 900, marginBottom: 8 }}>Recommendations</div>
              <div style={{ color: "#64748b", fontWeight: 600, marginBottom: 10 }}>
                Recommendations are derived from detected patterns.
              </div>
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {(payload?.insights || []).slice(0, 5).map((t, idx) => (
                  <li key={idx} style={{ marginBottom: 8, color: "#0f172a", fontWeight: 650 }}>
                    {t}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div style={{ marginTop: 14 }}>
            <OperationalIntelligenceCenter
              operationalIntelligence={payload?.operationalIntelligence ?? {}}
              summary={payload?.summary ?? {}}
              insights={payload?.insights ?? []}
              loading={false}
            />
          </div>


        </>

      )}
    </div>
  );
}

export default function InsightsPage() {
  return (
    <InsightsErrorBoundary>
      <InsightsPageInner />
    </InsightsErrorBoundary>
  );
}


