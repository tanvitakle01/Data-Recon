import ComingSoon from "../components/ComingSoon";

function DataSourcesPage() {
  return (
    <div>
      <h2 style={{ margin: 0, fontWeight: 900, letterSpacing: "-0.02em" }}>
        Data Sources
      </h2>
      <div style={{ color: "#64748b", marginTop: 6, fontWeight: 600 }}>
        Connect and validate source systems (SAP, SQL, Excel/CSV).
      </div>

      <ComingSoon note="This module will be expanded to support reusable connector configurations." />
    </div>
  );
}

export default DataSourcesPage;
