import { useState } from "react";
import { Tabs } from "@bristlecone/canopy";
import ComingSoon from "../components/ComingSoon";
import ConnectionsPage from "../settings/connections/ConnectionsPage";

const TABS = [
  { id: "connections", label: "Connections" },
  { id: "general", label: "General" },
];

function SettingsPage() {
  const [tab, setTab] = useState("connections");

  return (
    <div>
      <h2 style={{ margin: 0, fontWeight: 900, letterSpacing: "-0.02em" }}>Settings</h2>
      <div style={{ color: "#64748b", marginTop: 6, fontWeight: 600 }}>
        Configure environment, reconciliation rules, and AI preferences.
      </div>

      <div style={{ marginTop: 24 }}>
        <Tabs items={TABS} value={tab} onChange={setTab} />
        <div style={{ marginTop: 20 }}>
          {tab === "connections" && <ConnectionsPage />}
          {tab === "general" && (
            <ComingSoon note="Settings UI will be expanded once backend configuration endpoints are added." />
          )}
        </div>
      </div>
    </div>
  );
}

export default SettingsPage;
