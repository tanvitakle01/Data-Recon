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

      <div
        style={{
          border: "1px solid #e5e7eb",
          borderRadius: 12,
          overflow: "hidden",
          background: "#fff",
        }}
      >
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
          }}
        >
          <thead>
            <tr
              style={{
                background: "#f9fafb",
                textAlign: "left",
              }}
            >
              <th style={{ padding: 12 }}>Logical Field</th>
              <th style={{ padding: 12 }}>Source Column</th>
              <th style={{ padding: 12 }}>Target Column</th>
              <th style={{ padding: 12 }}>Role</th>
            </tr>
          </thead>

          <tbody>
            {mappingData.display.map((row, idx) => (
              <tr
                key={idx}
                style={{
                  borderTop: "1px solid #e5e7eb",
                }}
              >
                <td style={{ padding: 12 }}>{row.logical}</td>
                <td style={{ padding: 12 }}>{row.source_col}</td>
                <td style={{ padding: 12 }}>{row.target_col}</td>
                <td style={{ padding: 12 }}>{row.role}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default Mapping;