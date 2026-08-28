import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./app/AppLayout";
import { WizardProvider } from "./reconciliation/context/WizardContext";
import { AuthProvider } from "./auth/AuthContext";
import { useAuth } from "./auth/useAuth";
import RequireAuth from "./auth/RequireAuth";
import PublicLayout from "./auth/PublicLayout";
import AuthSplashLayout from "./auth/AuthSplashLayout";
import LoginPage from "./auth/LoginPage";
import LandingPage from "./marketing/LandingPage";
import SignUpPage from "./auth/SignUpPage";
import PasswordResetRequestPage from "./auth/PasswordResetRequestPage";
import PasswordResetConfirmPage from "./auth/PasswordResetConfirmPage";

import HomePage from "./pages/HomePage";
import ReconciliationWizardPage from "./reconciliation/ReconciliationWizardPage";
import InsightsPage from "./pages/InsightsPage";
import DataSourcesPage from "./pages/DataSourcesPage";
import SettingsPage from "./pages/SettingsPage";
import InsightsHistoryPage from "./pages/InsightsHistoryPage";
import LibraryPage from "./library/LibraryPage";
import StoredRunsPage from "./pages/StoredRunsPage";

// The authenticated app shell — unchanged from before auth was added, just
// gated behind AppRoutes below instead of being the only thing App() renders.
function AuthenticatedApp() {
  return (
    <WizardProvider>
      <AppLayout>
        <Routes>
          <Route path="/" element={<Navigate to="/home" replace />} />
          <Route path="/home" element={<HomePage />} />
          <Route path="/reconciliation/*" element={<ReconciliationWizardPage />} />
          <Route path="/insights" element={<InsightsPage />} />
          <Route path="/insights/history" element={<InsightsHistoryPage />} />
          <Route path="/insights/run/:runId" element={<InsightsPage />} />
          <Route path="/library" element={<LibraryPage />} />
          <Route path="/stored-runs" element={<StoredRunsPage />} />
          <Route path="/data-sources" element={<DataSourcesPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/home" replace />} />
        </Routes>
      </AppLayout>
    </WizardProvider>
  );
}

// Deliberately branches into two entirely separate <Routes> trees rather
// than nesting one inside the other — nested <Routes> resolve child paths
// relative to the parent's matched segment, which would silently break the
// existing absolute-looking paths above (e.g. "/home"). Branching here keeps
// both trees exactly as simple as they'd be standalone.
function AppRoutes() {
  const { status } = useAuth();

  if (status === "loading") {
    return null;
  }

  if (status === "anonymous") {
    return (
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route element={<AuthSplashLayout />}>
          <Route path="/login" element={<LoginPage />} />
        </Route>
        <Route element={<PublicLayout />}>
          <Route path="/signup" element={<SignUpPage />} />
          <Route path="/password-reset" element={<PasswordResetRequestPage />} />
          <Route path="/password-reset/confirm" element={<PasswordResetConfirmPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    );
  }

  return (
    <RequireAuth>
      <AuthenticatedApp />
    </RequireAuth>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
