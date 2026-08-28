import { Outlet, useNavigate } from "react-router-dom";
import "./authSplashLayout.css";

/** Full-bleed shell for "/login" only — split-panel PublicLayout stays in
 * use for signup/password-reset. No background photo asset exists yet, so
 * the backdrop is a CSS gradient anchored on the same --ink token instead of
 * an <img> that would 404. */
function AuthSplashLayout() {
  const navigate = useNavigate();

  return (
    <div className="auth-splash">
      <div className="auth-splash-backdrop" aria-hidden="true" />
      <div className="auth-splash-scrim" aria-hidden="true" />

      <div className="auth-splash-brand">
        <span className="auth-splash-brand-text">Data Reconciliation</span>
      </div>

      <div className="auth-splash-card">
        <Outlet />
      </div>

      <button type="button" className="auth-splash-back" onClick={() => navigate("/")}>
        ← Back to home
      </button>
    </div>
  );
}

export default AuthSplashLayout;
