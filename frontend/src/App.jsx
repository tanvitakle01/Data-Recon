import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./app/AppLayout";

import HomePage from "./pages/HomePage";
import ReconciliationEnginePage from "./pages/ReconciliationEnginePage";
import InsightsPage from "./pages/InsightsPage";
import DataSourcesPage from "./pages/DataSourcesPage";
import SettingsPage from "./pages/SettingsPage";
import InsightsHistoryPage from "./pages/InsightsHistoryPage";

function App() {
  return (
    <BrowserRouter>
      <AppLayout>
        <Routes>
          <Route path="/" element={<Navigate to="/home" replace />} />
          <Route path="/home" element={<HomePage />} />
          <Route path="/reconciliation" element={<ReconciliationEnginePage />} />
          <Route path="/insights" element={<InsightsPage />} />
          <Route path="/insights/history" element={<InsightsHistoryPage />} />
          <Route path="/data-sources" element={<DataSourcesPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/home" replace />} />
        </Routes>
      </AppLayout>
    </BrowserRouter>
  );
}

export default App;





