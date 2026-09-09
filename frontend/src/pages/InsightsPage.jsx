import React, { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import api from "../services/api";
import InsightsView from "../components/insights/InsightsView";
import SkeletonCards from "../components/insights/SkeletonCards";

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
  const { runId } = useParams();

  const mode = runId ? "fromRunId" : "upload";
  const isAutoMode = mode === "fromRunId";

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const [payload, setPayload] = useState(null);
  const [uploadId, setUploadId] = useState(null);

  const [uploadFile, setUploadFile] = useState(null);
  const [uploadDragOver, setUploadDragOver] = useState(false);
  const uploadInputRef = useRef(null);
  const [pdfBusy, setPdfBusy] = useState(false);

  const insightsSectionRef = useRef(null);

  const onDownloadPdf = async () => {
    setPdfBusy(true);
    try {
      const body = runId ? { run_id: runId } : { upload_id: uploadId };
      const res = await api.post("/insights/pdf", body, { responseType: "blob" });
      const blobUrl = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = `insights_${runId || uploadId}.pdf`;
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
      if (!runId) return;
      setBusy(true);
      setError(null);
      try {
        const res = await api.post("/insights/from-run-id", { run_id: runId });
        setPayload(res.data?.payload ?? null);

        requestAnimationFrame(() => {
          if (insightsSectionRef.current) {
            insightsSectionRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
          }
        });
      } catch (e) {
        setError(e?.response?.data?.detail || "Failed to generate insights");
      } finally {
        setBusy(false);
      }
    };

    runAuto();
  }, [runId]);

  const onUploadGenerate = async () => {
    if (!uploadFile) return;
    setBusy(true);
    setError(null);
    setPayload(null);
    setUploadId(null);

    try {
      const formData = new FormData();
      formData.append("file", uploadFile);

      const res = await api.post("/insights/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const data = res.data?.payload ?? null;
      setPayload(data);
      setUploadId(data?.uploadId ?? null);

      requestAnimationFrame(() => {
        if (insightsSectionRef.current) {
          insightsSectionRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
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
        {payload && (runId || uploadId) && (
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
          <div style={{ fontWeight: 850, marginBottom: 10 }}>Upload reconciliation results workbook</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 12, alignItems: "end" }}>
            <div>
              <label style={{ display: "block", color: "#475569", fontWeight: 800, fontSize: 13, marginBottom: 8 }}>
                Results workbook (.xlsx)
              </label>
              <div
                onClick={() => uploadInputRef.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault();
                  setUploadDragOver(true);
                }}
                onDragLeave={() => setUploadDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setUploadDragOver(false);
                  setUploadFile(e.dataTransfer.files?.[0] ?? null);
                }}
                style={{
                  border: `1.5px dashed ${uploadDragOver ? "#2563eb" : "rgba(148,163,184,0.6)"}`,
                  borderRadius: 10,
                  padding: 16,
                  textAlign: "center",
                  cursor: "pointer",
                  background: uploadDragOver ? "rgba(37,99,235,0.06)" : "transparent",
                }}
              >
                <div style={{ fontSize: 13, color: "#475569", fontWeight: 600 }}>
                  {uploadFile ? uploadFile.name : "Drag & drop the workbook here, or click to choose"}
                </div>
                <input
                  ref={uploadInputRef}
                  type="file"
                  accept=".xlsx,.xls"
                  onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                  style={{ display: "none" }}
                />
              </div>
              <div style={{ color: "#64748b", fontWeight: 600, marginTop: 6, fontSize: 12 }}>
                Upload the workbook downloaded from a completed reconciliation run — Summary / All Records / Mapping
                Details sheets. CSV isn't supported here since the workbook must carry these named sheets.
              </div>
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
        <div ref={insightsSectionRef} style={{ marginTop: 14 }}>
          <InsightsView payload={payload} runId={runId} uploadId={uploadId} />
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
