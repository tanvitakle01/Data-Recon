import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./app/AppLayout";
import { TicketingProvider } from "./ticketing/TicketingContext";
import { WizardProvider } from "./reconciliation/context/WizardContext";

import HomePage from "./pages/HomePage";
import ReconciliationWizardPage from "./reconciliation/ReconciliationWizardPage";
import InsightsPage from "./pages/InsightsPage";
import DataSourcesPage from "./pages/DataSourcesPage";
import SettingsPage from "./pages/SettingsPage";
import InsightsHistoryPage from "./pages/InsightsHistoryPage";
import TicketingPage from "./pages/TicketingPage";
import LibraryPage from "./library/LibraryPage";

function App() {
  return (
    <BrowserRouter>
      <TicketingProvider>
        <WizardProvider>
        <AppLayout>
          <Routes>
            <Route path="/" element={<Navigate to="/home" replace />} />
            <Route path="/home" element={<HomePage />} />
            <Route path="/reconciliation/*" element={<ReconciliationWizardPage />} />
            <Route path="/insights" element={<InsightsPage />} />
            <Route path="/insights/history" element={<InsightsHistoryPage />} />
            <Route path="/insights/run/:runId" element={<InsightsPage />} />
            <Route path="/ticketing" element={<TicketingPage />} />
            <Route path="/library" element={<LibraryPage />} />
            <Route path="/data-sources" element={<DataSourcesPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/home" replace />} />
          </Routes>
        </AppLayout>
        </WizardProvider>
      </TicketingProvider>
    </BrowserRouter>
  );
}

export default App;





