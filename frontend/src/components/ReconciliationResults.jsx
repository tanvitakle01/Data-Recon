import { useMemo } from "react";

function ReconciliationResults({ results }) {
  if (!results) return null;

  const rows = results.results ?? [];

  const columns = useMemo(() => {
    const first = (rows && rows[0]) || null;
    if (!first) return [];
    return Object.keys(first);
  }, [rows]);

  return (
    <div>
      <h2 style={{ fontSize: 16, margin: "18px 0 10px" }}>Reconciliation Results</h2>

      <div style={{ border: "1px solid #e5e7eb", borderRadius: 12, background: "white", padding: 12 }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>Results</div>
        <div style={{ maxHeight: 320, overflow: "auto" }}>
          <table style={{ borderCollapse: "collapse", width: "100%", minWidth: 520 }}>
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c} style={{ textAlign: "left", borderBottom: "1px solid #f3f4f6", padding: 8, background: "#f9fafb" }}>
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, idx) => (
                <tr key={idx}>
                  {columns.map((c) => (
                    <td key={c} style={{ borderBottom: "1px solid #f3f4f6", padding: 8, fontSize: 12, color: "#374151" }}>
                      {r?.[c] === null || r?.[c] === undefined ? "" : String(r[c])}
                    </td>
                  ))}
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={columns.length || 1} style={{ padding: 10, color: "#6b7280" }}>
                    No records.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Render exactly `result.results` rows returned by backend (no slicing, no derived counts). */}
    </div>
  );
}

export default ReconciliationResults;



