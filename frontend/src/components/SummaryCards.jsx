function SummaryCards({ summary }) {
  if (!summary) return null;

  const cardStyle = {
    border: "1px solid #e5e7eb",
    borderRadius: 12,
    padding: 14,
    background: "white",
  };

  const valueStyle = {
    fontSize: 22,
    fontWeight: 600,
    marginTop: 6,
  };

  const labelStyle = {
    fontSize: 12,
    color: "#6b7280",
    textTransform: "uppercase",
    letterSpacing: 0.04,
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
      <div style={cardStyle}>
        <div style={labelStyle}>Matched</div>
        <div style={valueStyle}>{summary.matched ?? 0}</div>
      </div>
      <div style={cardStyle}>
        <div style={labelStyle}>Qty Mismatch</div>
        <div style={valueStyle}>{summary.qty_mismatch ?? 0}</div>
      </div>
      <div style={cardStyle}>
        <div style={labelStyle}>Missing in Target</div>
        <div style={valueStyle}>{summary.missing_in_target ?? 0}</div>
      </div>
      <div style={cardStyle}>
        <div style={labelStyle}>Extra in Target</div>
        <div style={valueStyle}>{summary.extra_in_target ?? 0}</div>
      </div>
    </div>
  );
}

export default SummaryCards;

