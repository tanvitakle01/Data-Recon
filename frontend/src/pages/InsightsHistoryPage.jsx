import ComingSoon from "../components/ComingSoon";

function InsightsHistoryPage() {
  return (
    <div>
      <h2 style={{ margin: 0, fontWeight: 900, letterSpacing: "-0.02em" }}>
        Historical Reports
      </h2>
      <div style={{ color: "#64748b", marginTop: 6, fontWeight: 600 }}>
        View, download, and manage previously generated comparison reports.
      </div>

      <ComingSoon note="Backend metadata endpoints will be added in a later step." />
    </div>
  );
}

export default InsightsHistoryPage;
