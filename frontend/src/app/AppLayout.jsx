import { useMemo } from "react";
import { Link, useLocation } from "react-router-dom";
import { BristleconeLogo } from "@bristlecone/canopy";
import WizardStepBar from "./WizardStepBar";
import styles from "./appLayout.module.css";

// Destinations are a flat, always-visible row — the redesign drops the
// collapsible dark sidebar, so there is no rail to hide them behind and no
// expanded/collapsed preference to persist.
const NAV_ITEMS = [
  { key: "home", to: "/home", label: "Home" },
  { key: "reconciliation", to: "/reconciliation", label: "Reconciliation Engine" },
];

function AppLayout({ children }) {
  const location = useLocation();

  const activeKey = useMemo(() => {
    const p = location.pathname;
    if (p.startsWith("/reconciliation")) return "reconciliation";
    return "home";
  }, [location.pathname]);

  return (
    <div className={styles.shell}>
      {/* Sticky chrome: brand + section tabs, with the wizard's step bar as a
          second band while a reconciliation is open. Both stick together so
          the step bar stays visible down a long step. */}
      <header className={styles.topHeader}>
        <div className={styles.headerInner}>
          <Link to="/home" className={styles.brandRow} aria-label="Data Reconciliation home">
            <BristleconeLogo size="sm" />
            <span className={styles.brandDivider} aria-hidden="true" />
            <span className={styles.brandText}>Data Reconciliation</span>
          </Link>

          <nav className={styles.tabs} aria-label="Sections">
            {NAV_ITEMS.map((item) => (
              <Link
                key={item.key}
                to={item.to}
                className={`${styles.tab} ${activeKey === item.key ? styles.tabActive : ""}`}
                aria-current={activeKey === item.key ? "page" : undefined}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>

        {activeKey === "reconciliation" && <WizardStepBar />}
      </header>

      <main className={styles.main}>
        <div className={styles.mainInner}>{children}</div>
      </main>
    </div>
  );
}

export default AppLayout;
