import SummaryGrid from "./SummaryGrid";

function SummaryCards({ summary }) {
  if (!summary) return null;

  const metrics = [
    { label: "Matched", value: summary.matched ?? 0 },
    { label: "Qty Mismatch", value: summary.qty_mismatch ?? 0 },
    { label: "Missing in Target", value: summary.missing_in_target ?? 0 },
    { label: "Extra in Target", value: summary.extra_in_target ?? 0 },
  ];

  return (
    <div>
      <h4 style={{ margin: "0 0 14px 0", fontWeight: 650, color: "var(--ink)" }}>
        Summary
      </h4>
      <SummaryGrid metrics={metrics} />
    </div>
  );
}


export default SummaryCards;

