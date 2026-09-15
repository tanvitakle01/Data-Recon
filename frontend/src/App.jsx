import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./app/AppLayout";
import { WizardProvider } from "./reconciliation/context/WizardContext";

import HomePage from "./pages/HomePage";
import ReconciliationWizardPage from "./reconciliation/ReconciliationWizardPage";

function App() {
  return (
    <BrowserRouter>
      <WizardProvider>
        <AppLayout>
          <Routes>
            <Route path="/" element={<Navigate to="/home" replace />} />
            <Route path="/home" element={<HomePage />} />
            <Route path="/reconciliation/*" element={<ReconciliationWizardPage />} />
            <Route path="*" element={<Navigate to="/home" replace />} />
          </Routes>
        </AppLayout>
      </WizardProvider>
    </BrowserRouter>
  );
}

export default App;
