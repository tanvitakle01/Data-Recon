import { useMemo, useState } from "react";
import api from "../services/api";
import PreviewTable from "./PreviewTable";
import IBPDatasetBuilder from "./IBPDatasetBuilder";

function SAPFetchSection({ onSourceLoaded }) {
  const [loadingS4, setLoadingS4] = useState(false);

  const [error, setError] = useState(null);

  const [s4Source, setS4Source] = useState(null);
  const [ibpSource, setIBPSource] = useState(null);

  const [showS4Preview, setShowS4Preview] = useState(false);

  const counts = useMemo(() => {
    return {
      s4Rows: s4Source?.rows ?? 0,
    };
  }, [s4Source]);

  const fetchFromSAP = async () => {
    setError(null);
    setLoadingS4(true);

    try {
      const response = await api.get("/api/s4/test-preview");

      const payload = response.data ?? {};

      if (!payload?.success) {
        setError(payload?.error || "S/4 Connection Failed");
        return;
      }

      const data = payload.data ?? [];

      const transformedSource = {
        rows: data.length,
        columns: ["Material", "Plnt", "ReqDlvDate", "ReqDlvQty"],
        preview: data.slice(0, 10),
        data: data, // Store the full data for later use
      };

      console.log("S4 Preview:", transformedSource);

      setS4Source(transformedSource);

      onSourceLoaded?.({
        s4: transformedSource,
        ibp: ibpSource,
      });
    } catch (err) {
      console.error("S4 Fetch Error:", err);

      const msg = err?.message ? err.message : String(err);

      setError(`S/4 fetch failed: ${msg}`);
    } finally {
      setLoadingS4(false);
    }
  };

  const handleIBPDataset = (source) => {
    setIBPSource(source);

    onSourceLoaded?.({
      s4: s4Source,
      ibp: source,
    });
  };

  return (
    <div>
      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <button onClick={fetchFromSAP} disabled={loadingS4} className="btn-primary">
          {loadingS4 ? "Fetching S/4..." : "Fetch From S/4"}
        </button>
      </div>

      <div style={{ marginTop: 20 }}>
        <div style={{ fontWeight: 800, marginBottom: 10, color: "#334155" }}>
          Target System — SAP IBP
        </div>
        <IBPDatasetBuilder onDatasetLoaded={handleIBPDataset} />
      </div>

      {error && (
        <div style={{ marginTop: 12, color: "#b91c1c" }}>
          ⚠️ {String(error)}
        </div>
      )}

      {s4Source && (
        <div style={{ marginTop: 14 }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <span
              style={{
                display: "inline-flex",
                padding: "4px 12px",
                borderRadius: 999,
                fontSize: 12,
                fontWeight: 800,
                background: "rgba(16,185,129,0.12)",
                color: "#047857",
              }}
            >
              S/4 loaded · {counts.s4Rows} rows
            </span>
          </div>

          <div
            style={{
              display: "flex",
              gap: 10,
              marginTop: 12,
              flexWrap: "wrap",
            }}
          >
            <button className="btn-secondary" onClick={() => setShowS4Preview((s) => !s)}>
              {showS4Preview ? "Hide" : "Preview"} S/4 Data
            </button>
          </div>

          {showS4Preview && (
            <PreviewTable
              data={s4Source}
              title="S/4 Preview (first 10 rows)"
            />
          )}
        </div>
      )}
    </div>
  );
}

export default SAPFetchSection;