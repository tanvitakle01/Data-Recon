import PreviewTable from "./PreviewTable";

function roleBadge(role) {
  const r = String(role || "").toLowerCase();
  if (r.includes("key")) return "🔑 Key";
  if (r.includes("compare")) return "📊 Compare";
  return role;
}

function MappingTable({ display }) {
  if (!Array.isArray(display) || display.length === 0) return null;

  return (
    <div style={{ marginTop: 20 }}>
      <h3 style={{ marginBottom: 10 }}>Detected Column Mapping</h3>

      <div style={{ overflowX: "auto" }}>
        <table
          border="1"
          cellPadding="8"
          style={{ borderCollapse: "collapse", width: "100%", minWidth: 720 }}
        >
          <thead>
            <tr>
              <th>Logical Field</th>
              <th>Source Column</th>
              <th>Target Column</th>
              <th>Role</th>
            </tr>
          </thead>
          <tbody>
            {display.map((row, idx) => (
              <tr key={idx}>
                <td>{row.logical_field ?? row.logical ?? ""}</td>
                <td>{row.source_column ?? row.source ?? ""}</td>
                <td>{row.target_column ?? row.target ?? ""}</td>
                <td>{roleBadge(row.role)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default MappingTable;

