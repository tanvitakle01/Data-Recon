function DataSourcesPage() {
  return (
    <div style={{ maxWidth: 1200, margin: "0 auto" }}>
      <h2 style={{ margin: 0, fontWeight: 900, letterSpacing: "-0.02em" }}>
        Data Sources
      </h2>
      <div style={{ color: "#64748b", marginTop: 6, fontWeight: 600 }}>
        Connect and validate source systems (SAP, SQL, Excel/CSV).
      </div>

      <div style={{ marginTop: 18, background: "rgba(255,255,255,0.8)", border: "1px solid rgba(148,163,184,0.25)", borderRadius: 18, padding: 16 }}>
        <div style={{ fontWeight: 850, marginBottom: 6 }}>Coming soon</div>
        <div style={{ color: "#64748b", fontWeight: 600 }}>
          This module will be expanded to support reusable connector configurations.
        </div>
      </div>
    </div>
  );
}

export default DataSourcesPage;

