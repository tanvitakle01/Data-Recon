import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

function ReconciliationResults({ reconResult }) {
  const navigate = useNavigate();
  const { preview_rows: previewRows, file, file_id: fileId } = reconResult || {};

  const [scenario, setScenario] = useState("All");

  const scenarioToRemarksPrefixKey = useMemo(
    () => ({
      All: null,
      Matched: "MATCH",
      "Qty Mismatch": "QTY_MISMATCH",
      "Missing in Target": "MISSING_IN_TARGET",
      "Extra in Target": "EXTRA_IN_TARGET",
    }),
    [],
  );

  const filteredPreview = useMemo(() => {
    const rows = Array.isArray(previewRows)
      ? previewRows
      : previewRows?.preview;
    if (!Array.isArray(rows)) return [];

    const wantedKey = scenarioToRemarksPrefixKey[scenario];
    if (!wantedKey) return rows;

    const prefixMap = {
      MATCH: "✅ MATCH",
      QTY_MISMATCH: "⚠️ QTY MISMATCH",
      MISSING_IN_TARGET: "❌ MISSING IN TARGET",
      EXTRA_IN_TARGET: "🔶 EXTRA IN TARGET",
    };

    const wantedPrefix = prefixMap[wantedKey];
    return rows.filter((r) => {
      const remarks = r?.Remarks ?? r?.remarks ?? r?.remark ?? "";
      return String(remarks).startsWith(wantedPrefix);
    });
  }, [previewRows, scenario, scenarioToRemarksPrefixKey]);

  const columns = useMemo(() => {
    if (!filteredPreview?.length) return [];
    const first = filteredPreview[0] || {};
    return Object.keys(first);
  }, [filteredPreview]);

  const downloadUrl = file?.download_url;
  const hasFilename = !!file?.filename;

  const canViewInsights = !!fileId;

  return (
    <div style={{ marginTop: 16 }}>
      <h4 style={{ margin: "0 0 12px 0" }}>Comparison complete</h4>

      <div
        style={{
          marginBottom: 12,
          display: "flex",
          gap: 10,
          alignItems: "center",
        }}
      >
        <div style={{ color: "#64748b", fontSize: 13, fontWeight: 600 }}>Scenario</div>
        <select
          value={scenario}
          onChange={(e) => setScenario(e.target.value)}
          style={{
            padding: "8px 12px",
            borderRadius: 10,
            border: "1px solid rgba(148,163,184,0.35)",
            background: "#fff",
            fontWeight: 700,
            color: "#0f172a",
          }}
        >
          <option value="All">All</option>
          <option value="Matched">Matched</option>
          <option value="Qty Mismatch">Qty Mismatch</option>
          <option value="Missing in Target">Missing in Target</option>
          <option value="Extra in Target">Extra in Target</option>
        </select>
      </div>

      {Array.isArray(filteredPreview) && filteredPreview.length > 0 && columns.length > 0 ? (
        <div className="surface-elevated" style={{ marginTop: 8, maxHeight: 320, overflow: "auto" }}>
          <table className="table-elevated" style={{ minWidth: Math.max(600, columns.length * 120) }}>
            <thead>
              <tr>
                {columns.map((col) => (
                  <th key={col} style={{ position: "sticky", top: 0, background: "#f8fafc" }}>
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredPreview.map((row, idx) => (
                <tr key={idx}>
                  {columns.map((col) => (
                    <td key={col}>{String(row?.[col] ?? "")}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div style={{ marginTop: 12, color: "#64748b" }}>
          No preview rows available for the selected scenario.
        </div>
      )}

      {hasFilename && (
        <div style={{ marginTop: 18, marginBottom: 6 }}>
          <div style={{ marginBottom: 6, color: "#64748b", fontSize: 13 }}>
            Comparison complete. File ready for download.
          </div>

          <div style={{ marginBottom: 6, fontSize: 14, fontWeight: 600 }}>{file.filename}</div>

          {downloadUrl ? (
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button
                type="button"
                onClick={async () => {
                  try {
                    const downloadEndpoint = downloadUrl.startsWith("http")
                      ? downloadUrl
                      : `http://localhost:8000${downloadUrl}`;

                    const res = await fetch(downloadEndpoint, {
                      method: "GET",
                      cache: "no-store",
                    });

                    if (!res.ok) {
                      let bodyText = "";
                      try {
                        bodyText = await res.text();
                      } catch {
                        // ignore parsing errors
                      }
                      throw new Error(
                        `Download failed: ${res.status}. ${bodyText ? `Body: ${bodyText}` : ""}`,
                      );
                    }

                    const blob = await res.blob();
                    const url = window.URL.createObjectURL(blob);

                    const a = document.createElement("a");
                    a.href = url;
                    a.download = file?.filename || "download.xlsx";
                    document.body.appendChild(a);
                    a.click();
                    a.remove();

                    setTimeout(() => {
                      window.URL.revokeObjectURL(url);
                    }, 1000);
                  } catch (err) {
                    console.error(err);
                    alert(String(err?.message || "Download failed"));
                  }
                }}
                className="btn-primary"
              >
                Download Results
              </button>

              {canViewInsights && (
                <button
                  type="button"
                  onClick={() => navigate(`/insights?file_id=${encodeURIComponent(fileId)}`)}
                  className="btn-secondary"
                >
                  View Insights
                </button>
              )}
            </div>
          ) : (
            <div style={{ color: "#64748b", fontSize: 13, marginTop: 8 }}>
              Download is not available yet.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ReconciliationResults;

