function PreviewTable({ data, title }) {
  if (!data || !data.columns || !data.preview) return null;

  return (
    <div style={{ marginTop: 16 }}>
      <h4 style={{ marginBottom: 8 }}>{title || "Preview (first 5 rows)"}</h4>

      <div className="surface-elevated" style={{ maxHeight: 300, overflow: "auto" }}>
        <table className="table-elevated" style={{ minWidth: 600 }}>
          <thead>
            <tr>
              {data.columns.map((col) => (
                <th key={col}>{col}</th>
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
