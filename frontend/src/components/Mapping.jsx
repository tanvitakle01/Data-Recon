function Mapping({ mappingData, loading, error }) {
  if (loading) {
    return (
      <div style={{ marginTop: 20 }}>
        <h3>Detected Column Mapping</h3>
        <div>Detecting mapping...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ marginTop: 20 }}>
        <h3>Detected Column Mapping</h3>
        <div style={{ color: "#dc2626" }}>
          ⚠️ Failed to detect column mapping
        </div>
      </div>
    );
  }

  if (
    !mappingData ||
    !mappingData.display ||
    mappingData.display.length === 0
  ) {
    return null;
  }

  return (
    <div style={{ marginTop: 24 }}>
      <h3 style={{ marginBottom: 6 }}>Detected Column Mapping</h3>

      <p
        style={{
          color: "#6b7280",
          marginBottom: 16,
          fontSize: 14,
        }}
      >
        Key columns identify matching rows. The compare column is checked for
        quantity differences.
      </p>

      <div className="surface-elevated" style={{ overflow: "hidden" }}>
        <table className="table-elevated">
          <thead>
            <tr>
              <th>Source Column</th>
              <th>Target Column</th>
              <th>Role</th>
            </tr>
          </thead>

          <tbody>
            {mappingData.display.map((row, idx) => (
              <tr key={idx}>
                <td>{row.source_col}</td>
                <td>{row.target_col}</td>
                <td>
                  <span
                    style={{
                      display: "inline-flex",
                      padding: "3px 10px",
                      borderRadius: 999,
                      fontSize: 12,
                      fontWeight: 800,
                      background: String(row.role).toLowerCase().includes("key") ? "rgba(59,130,246,0.12)" : "rgba(16,185,129,0.12)",
                      color: String(row.role).toLowerCase().includes("key") ? "#1d4ed8" : "#047857",
                    }}
                  >
                    {row.role}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default Mapping;
