function PreviewTable({ data, title }) {
  if (!data || !data.columns || !data.preview) return null;

  return (
    <div style={{ marginTop: 16, overflowX: "auto" }}>
      <h4 style={{ marginBottom: 8 }}>{title || "Preview (first 5 rows)"}</h4>


      <div style={{ maxHeight: 300, overflow: "auto" }}>
        <table
          border="1"
          cellPadding="8"
          style={{ borderCollapse: "collapse", width: "100%", minWidth: 600 }}
        >
          <thead>
            <tr>
              {data.columns.map((col) => (
                <th key={col} style={{ position: "sticky", top: 0, background: "#f3f4f6" }}>
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.preview.map((row, idx) => (
              <tr key={idx}>
                {data.columns.map((col) => (
                  <td key={col}>{row[col]}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default PreviewTable;

