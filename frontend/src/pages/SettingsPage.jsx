import ComingSoon from "../components/ComingSoon";

function SettingsPage() {
  return (
    <div>
      <h2 style={{ margin: 0, fontWeight: 900, letterSpacing: "-0.02em" }}>
        Settings
      </h2>
      <div style={{ color: "#64748b", marginTop: 6, fontWeight: 600 }}>
        Configure environment, reconciliation rules, and AI preferences.
      </div>

      <ComingSoon note="Settings UI will be expanded once backend configuration endpoints are added." />
    </div>
  );
}

export default SettingsPage;
