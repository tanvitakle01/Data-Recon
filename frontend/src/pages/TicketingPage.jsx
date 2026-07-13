import { useState } from "react";
import TicketingTabs from "../components/ticketing/TicketingTabs";
import TicketDashboardTab from "../components/ticketing/TicketDashboardTab";
import TeamsTab from "../components/ticketing/teams/TeamsTab";
import RoutingRulesEditor from "../components/ticketing/RoutingRulesEditor";

const TABS = [
  { id: "tickets", label: "Tickets" },
  { id: "teams", label: "Teams & Members" },
  { id: "routing", label: "Routing Rules" },
];

export default function TicketingPage() {
  const [activeTab, setActiveTab] = useState("tickets");

  return (
    <div>
      <TicketingTabs tabs={TABS} active={activeTab} onChange={setActiveTab} />
      <div key={activeTab} className="animate-[fadeIn_200ms_ease-out]">
        {activeTab === "tickets" ? <TicketDashboardTab /> : null}
        {activeTab === "teams" ? <TeamsTab /> : null}
        {activeTab === "routing" ? <RoutingRulesEditor /> : null}
      </div>
    </div>
  );
}
