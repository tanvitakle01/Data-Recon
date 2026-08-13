import { Outlet } from "react-router-dom";
import "./publicLayout.css";

/** Unauthenticated shell — split layout, brand panel one side, form the
 * other. Deliberately NOT AppLayout: no sidebar, no nav, nothing that
 * implies an active session. */
function PublicLayout() {
  return (
    <div className="public-layout">
      <div className="public-layout__brand">
        <div className="public-layout__brand-inner">
          <span className="public-layout__brand-mark">Data Reconciliation</span>
          <p className="public-layout__tagline">
            Enterprise reconciliation, mapping, and insight — one connected workspace.
          </p>
        </div>
      </div>
      <div className="public-layout__form">
        <div className="public-layout__form-inner">
          <Outlet />
        </div>
      </div>
    </div>
  );
}

export default PublicLayout;
