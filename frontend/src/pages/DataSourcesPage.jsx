import ConnectionsPage from "../datasources/connections/ConnectionsPage";

function DataSourcesPage() {
  return (
    <div>
      <h2 style={{ margin: 0, fontWeight: 900, letterSpacing: "-0.02em" }}>
        Data Sources
      </h2>
      <div style={{ color: "#64748b", marginTop: 6, fontWeight: 600 }}>
        Connect and validate source systems (SAP, SQL, Excel/CSV).
      </div>

      <div style={{ marginTop: 24 }}>
        <ConnectionsPage />
      </div>
    </div>
  );
}

export default DataSourcesPage;
