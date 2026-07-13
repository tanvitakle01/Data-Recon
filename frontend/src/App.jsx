import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./app/AppLayout";
import { TicketingProvider } from "./ticketing/TicketingContext";

import HomePage from "./pages/HomePage";
import ReconciliationWizardPage from "./reconciliation/ReconciliationWizardPage";
import InsightsPage from "./pages/InsightsPage";
import DataSourcesPage from "./pages/DataSourcesPage";
import SettingsPage from "./pages/SettingsPage";
import InsightsHistoryPage from "./pages/InsightsHistoryPage";
import TicketingPage from "./pages/TicketingPage";

function App() {
  return (
    <BrowserRouter>
      <TicketingProvider>
        <AppLayout>
          <Routes>
            <Route path="/" element={<Navigate to="/home" replace />} />
            <Route path="/home" element={<HomePage />} />
            <Route path="/reconciliation/*" element={<ReconciliationWizardPage />} />
            <Route path="/insights" element={<InsightsPage />} />
            <Route path="/insights/history" element={<InsightsHistoryPage />} />
            <Route path="/insights/run/:runId" element={<InsightsPage />} />
            <Route path="/ticketing" element={<TicketingPage />} />
            <Route path="/data-sources" element={<DataSourcesPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/home" replace />} />
          </Routes>
        </AppLayout>
      </TicketingProvider>
    </BrowserRouter>
  );
}

export default App;





