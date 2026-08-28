import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import api from "../services/api";
import CommandCenter from "../components/cockpit/CommandCenter";
import InsightsTabs from "../components/cockpit/InsightsTabs";
import ExecutiveSummaryView from "../components/executive/ExecutiveSummaryView";
import SkeletonCards from "../components/insights/SkeletonCards";

function useQuery() {
  const { search } = useLocation();
  return useMemo(() => new URLSearchParams(search), [search]);
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
  const { runId } = useParams();
  const fileId = query.get("file_id");

  const mode = runId ? "fromRunId" : fileId ? "fromFileId" : "upload";
  const isAutoMode = mode === "fromRunId" || mode === "fromFileId";

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const [payload, setPayload] = useState(null);
  const [activeTab, setActiveTab] = useState("executive");

  const [uploadFile, setUploadFile] = useState(null);
  const [uploadSheetName, setUploadSheetName] = useState("");
  const [pdfBusy, setPdfBusy] = useState(false);

  const cockpitSectionRef = useRef(null);

  const onDownloadPdf = async () => {
    if (!runId) return;
    setPdfBusy(true);
    try {
      const res = await api.get(`/insights/${runId}/pdf`, { responseType: "blob" });
      const blobUrl = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = `insights_${runId}.pdf`;
      a.click();
      URL.revokeObjectURL(blobUrl);
    } catch (e) {
      setError(e?.response?.data?.detail || "Failed to generate the PDF report");
    } finally {
      setPdfBusy(false);
    }
  };

  useEffect(() => {
    const runAuto = async () => {
      if (!runId && !fileId) return;
      setBusy(true);
      setError(null);
      try {
        const res = runId
          ? await api.post("/insights/from-run-id", { run_id: runId })
          : await api.post("/insights/from-file-id", { file_id: fileId });
        const data = res.data?.payload ?? null;
        setPayload(data);

        requestAnimationFrame(() => {
          if (cockpitSectionRef.current) {
            cockpitSectionRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
          }
        });
      } catch (e) {
        setError(e?.response?.data?.detail || "Failed to generate insights");
      } finally {
        setBusy(false);
      }
    };

    runAuto();
  }, [runId, fileId]);

  const onUploadGenerate = async () => {
    if (!uploadFile) return;
    setBusy(true);
    setError(null);
    setPayload(null);

    try {
      const formData = new FormData();
      formData.append("file", uploadFile);
      formData.append("sheet_name", uploadSheetName);

      const res = await api.post("/insights", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const data = res.data?.payload ?? null;
      setPayload(data);

      requestAnimationFrame(() => {
        if (cockpitSectionRef.current) {
          cockpitSectionRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      });
    } catch (e) {
      setError(e?.response?.data?.detail || "Insights generation failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div style={{ marginBottom: 16, display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div>
          <h2 style={{ margin: 0, fontWeight: 900, letterSpacing: "-0.02em" }}>Insights</h2>
          <div style={{ color: "#64748b", marginTop: 6, fontWeight: 600 }}>
            {isAutoMode ? "Auto-generated from reconciliation output" : "Standalone analysis"}
          </div>
        </div>
        {runId && payload && (
          <button
            type="button"
            onClick={onDownloadPdf}
            disabled={pdfBusy}
            className="btn-secondary"
            style={{ flex: "0 0 auto" }}
          >
            {pdfBusy ? "Preparing…" : "Download PDF"}
          </button>
        )}
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

      {busy && isAutoMode && (
        <div style={{ marginTop: 14 }}>
          <div style={{ color: "#64748b", fontWeight: 800, marginBottom: 10 }}>Generating insights…</div>
          <SkeletonCards />
        </div>
      )}

      {payload && (
        <div ref={cockpitSectionRef} style={{ marginTop: 14 }}>
          <InsightsTabs active={activeTab} onChange={setActiveTab} />
          <div key={activeTab} className="animate-[fadeIn_200ms_ease-out]">
            {activeTab === "executive" ? (
              <ExecutiveSummaryView payload={payload} fileId={fileId} runId={runId} />
            ) : (
              <CommandCenter payload={payload} fileId={fileId} runId={runId} />
            )}
          </div>
        </div>
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
