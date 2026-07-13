function ReconciliationScopeToggle({ value, onChange }) {
  const options = [
    { key: "overlap", label: "Overlapping Period Only (Recommended)" },
    { key: "full", label: "Full Dataset" },
  ];

  return (
    <div style={{ marginTop: 16, marginBottom: 8 }}>
      <div style={{ fontWeight: 800, fontSize: 13, color: "#334155", marginBottom: 8 }}>
        Reconciliation Scope
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {options.map((opt) => (
          <label
            key={opt.key}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              cursor: "pointer",
              fontSize: 13,
              fontWeight: 600,
              color: value === opt.key ? "#0f172a" : "#64748b",
            }}
          >
            <input
              type="radio"
              name="reconciliation-scope"
              value={opt.key}
              checked={value === opt.key}
              onChange={() => onChange(opt.key)}
            />
            {opt.label}
          </label>
        ))}
      </div>
    </div>
  );
}

export default ReconciliationScopeToggle;
