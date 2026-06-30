import { useMemo, useState } from "react";
import api from "../services/api";
import PreviewTable from "./PreviewTable";

// Source-only SAP fetch section for the existing Reconciliation page.
// It returns data in the same shape as the Excel preview payload.
function SAPFetchSection({ onSourceLoaded }) {

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [loaded, setLoaded] = useState(false);
  const [source, setSource] = useState(null);

  const [showSourcePreview, setShowSourcePreview] = useState(false);

  const counts = useMemo(() => {
    return {
      s4Rows: source?.rows ?? 0,
    };
  }, [source]);

  const fetchFromSAP = async () => {
    setError(null);
    setLoading(true);

    try {
      // Use the existing API service layer (no hardcoded localhost URLs)
      // Backend contract for this repo is currently: GET /api/s4/test-preview
      const response = await api.get("/api/s4/test-preview");
      const payload = response.data ?? {};
      if (!payload?.success) {
        setError(payload?.error || "Connection Failed");
        return;
      }
      const data = payload.data ?? [];


      // Convert to PreviewTable format expected by reconciliation page.
      // Backend /api/s4/test-preview now returns IBP-style keys for reconciliation MVP.
      // PreviewTable expects shape: { columns: [...], preview: [...] }
      const transformedSource = {
        rows: data.length,
        columns: ["Material", "Plnt", "ReqDlvDate", "ReqDlvQty"],
        preview: (data || []).slice(0, 10),
      };



      // Debug: ensure the UI is receiving the expected keys/values
      console.log("SAPFetchSection FULL body.data[0]", (data && data[0]) || null);
      console.log("SAPFetchSection transformedSource", transformedSource);





      setSource(transformedSource);
      setLoaded(true);
      setShowSourcePreview(false);

      onSourceLoaded?.(transformedSource);
    } catch (err) {
      console.error("SAP Fetch Error:", err);
      const msg = err?.message ? err.message : String(err);
      setError(`SAP fetch failed: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <button
          onClick={fetchFromSAP}
          disabled={loading}
          style={{
            padding: "10px 18px",
            borderRadius: 10,
            border: "1px solid #6b7280",
            background: loading ? "#f3f4f6" : "#111827",
            color: loading ? "#6b7280" : "white",
            cursor: loading ? "not-allowed" : "pointer",
          }}
        >
          {loading ? "Fetching…" : "Fetch From SAP"}
        </button>
      </div>

      {error && (
        <div style={{ marginTop: 12, color: "#b91c1c" }}>⚠️ {String(error)}</div>
      )}

      {loaded && (
        <div style={{ marginTop: 14 }}>
          <div>S/4 data loaded ({counts.s4Rows} rows)</div>

          <div style={{ display: "flex", gap: 10, marginTop: 12, flexWrap: "wrap" }}>
            <button
              style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid #ddd" }}
              onClick={() => setShowSourcePreview((s) => !s)}
              disabled={!source}
            >
              Preview S/4 Data
            </button>
          </div>

            {showSourcePreview && source && (
            <PreviewTable data={source} title="S/4 Preview (first 10 rows)" />
          )}

        </div>
      )}
    </div>
  );
}

export default SAPFetchSection;

