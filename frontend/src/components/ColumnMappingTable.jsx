function ColumnMappingTable({ mappings }) {
  if (!mappings?.length) return null;

  return (
    <div>
      <h2 style={{ fontSize: 16, marginBottom: 10 }}>Detected Column Mapping</h2>

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 700 }}>
          <thead>
            <tr>
              <th style={thStyle}>Logical Field</th>
              <th style={thStyle}>Source Column</th>
              <th style={thStyle}>Target Column</th>
              <th style={thStyle}>Role</th>
              <th style={thStyle}>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {mappings.map((m, idx) => (
              <tr key={idx}>
                <td style={tdStyle}>{m.logical ?? ""}</td>
                <td style={tdStyle}>{m.source}</td>
                <td style={tdStyle}>{m.target}</td>
                <td style={tdStyle}>{m.role ?? ""}</td>
                <td style={tdStyle}>{Math.round((m.score ?? 0) * 100)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}


const thStyle = {
  textAlign: "left",
  padding: 10,
  borderBottom: "1px solid #e5e7eb",
  background: "#f3f4f6",
};

const tdStyle = {
  padding: 10,
  borderBottom: "1px solid #f3f4f6",
};

export default ColumnMappingTable;

