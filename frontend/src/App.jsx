import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./app/AppLayout";
import { WizardProvider } from "./reconciliation/context/WizardContext";

import HomePage from "./pages/HomePage";
import ReconciliationWizardPage from "./reconciliation/ReconciliationWizardPage";
import ConnectionsPage from "./pages/ConnectionsPage";
import DocsArchitecturePage from "./pages/DocsArchitecturePage";

function App() {
  return (
    <BrowserRouter>
      <WizardProvider>
        <AppLayout>
          <Routes>
            <Route path="/" element={<Navigate to="/home" replace />} />
            <Route path="/home" element={<HomePage />} />
            <Route path="/reconciliation/*" element={<ReconciliationWizardPage />} />
            <Route path="/connections" element={<ConnectionsPage />} />
            <Route path="/docs/architecture" element={<DocsArchitecturePage />} />
            <Route path="*" element={<Navigate to="/home" replace />} />
          </Routes>
        </AppLayout>
      </WizardProvider>
    </BrowserRouter>
  );
}

export default App;
