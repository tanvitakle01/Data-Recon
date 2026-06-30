function SettingsPage() {
  return (
    <div style={{ maxWidth: 1200, margin: "0 auto" }}>
      <h2 style={{ margin: 0, fontWeight: 900, letterSpacing: "-0.02em" }}>
        Settings
      </h2>
      <div style={{ color: "#64748b", marginTop: 6, fontWeight: 600 }}>
        Configure environment, reconciliation rules, and AI preferences.
      </div>

      <div
        style={{
          marginTop: 18,
          background: "rgba(255,255,255,0.8)",
          border: "1px solid rgba(148,163,184,0.25)",
          borderRadius: 18,
          padding: 16,
        }}
      >
        <div style={{ fontWeight: 850 }}>Coming soon</div>
        <div style={{ color: "#64748b", fontWeight: 600, marginTop: 6 }}>
          Settings UI will be expanded once backend configuration endpoints are added.
        </div>
      </div>
    </div>
  );
}

export default SettingsPage;

