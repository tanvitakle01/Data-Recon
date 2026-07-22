import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  FiHome,
  FiLayers,
  FiBarChart2,
  FiDatabase,
  FiSettings,
  FiSidebar,
  FiMenu,
  FiX,
  FiClipboard,
  FiBookOpen,
} from "react-icons/fi";
import WizardSidebarNav from "../reconciliation/components/WizardSidebarNav";
import styles from "./appLayout.module.css";

const SIDEBAR_STORAGE_KEY = "sidebar-expanded";
// Below this width the sidebar auto-collapses to the icon rail so data tables
// keep their room; above it, the user's saved preference wins.
const AUTO_COLLAPSE_WIDTH = 1024;

function NavItem({ to, icon: Icon, label, active }) {
  return (
    <Link
      to={to}
      className={`${styles.item} ${active ? styles.itemActive : ""}`}
      aria-current={active ? "page" : undefined}
      aria-label={label}
      data-tooltip={label}
    >
      <span className={styles.itemIconWrap}>
        <Icon className={styles.itemIcon} />
      </span>
      <span className={styles.itemLabel}>{label}</span>
    </Link>
  );
}

function AppLayout({ children }) {
  const location = useLocation();

  const [prefExpanded, setPrefExpanded] = useState(() => {
    if (typeof window === "undefined") return true;
    const saved = window.localStorage.getItem(SIDEBAR_STORAGE_KEY);
    return saved === null ? true : saved === "true";
  });
  // Viewport-driven forced collapse (independent of the saved preference).
  const [autoCollapsed, setAutoCollapsed] = useState(
    () => typeof window !== "undefined" && window.innerWidth < AUTO_COLLAPSE_WIDTH
  );
  const [mobileOpen, setMobileOpen] = useState(false);

  const expanded = prefExpanded && !autoCollapsed;

  const activeKey = useMemo(() => {
    const p = location.pathname;
    if (p.startsWith("/reconciliation")) return "reconciliation";
    if (p.startsWith("/insights")) return "insights";
    if (p.startsWith("/library")) return "library";
    if (p.startsWith("/ticketing")) return "ticketing";
    if (p.startsWith("/data-sources")) return "data-sources";
    if (p.startsWith("/settings")) return "settings";
    return "home";
  }, [location.pathname]);

  const isWizard = activeKey === "reconciliation";

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(prefExpanded));
  }, [prefExpanded]);

  useEffect(() => {
    const onResize = () => setAutoCollapsed(window.innerWidth < AUTO_COLLAPSE_WIDTH);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    if (!mobileOpen) return undefined;
    const onKeyDown = (e) => {
      if (e.key === "Escape") setMobileOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [mobileOpen]);

  const navItems = [
    { key: "home", to: "/home", icon: FiHome, label: "Home" },
    { key: "reconciliation", to: "/reconciliation", icon: FiLayers, label: "Reconciliation Engine" },
    { key: "insights", to: "/insights", icon: FiBarChart2, label: "Insights" },
    { key: "library", to: "/library", icon: FiBookOpen, label: "Mapping Library" },
    { key: "ticketing", to: "/ticketing", icon: FiClipboard, label: "Ticketing" },
    { key: "data-sources", to: "/data-sources", icon: FiDatabase, label: "Data Sources" },
    { key: "settings", to: "/settings", icon: FiSettings, label: "Settings" },
  ];

  return (
    <div className={styles.shell}>
      <button
        type="button"
        className={styles.mobileMenuBtn}
        onClick={() => setMobileOpen(true)}
        aria-label="Open navigation menu"
        aria-expanded={mobileOpen}
      >
        <FiMenu />
      </button>

      <div
        className={`${styles.backdrop} ${mobileOpen ? styles.backdropVisible : ""}`}
        onClick={() => setMobileOpen(false)}
        aria-hidden="true"
      />

      <aside
        className={`${styles.sidebar} ${expanded ? styles.sidebarExpanded : styles.sidebarCollapsed} ${
          mobileOpen ? styles.sidebarMobileOpen : ""
        }`}
        aria-label="Primary navigation"
      >
        <div className={styles.sidebarTop}>
          <Link to="/home" className={styles.brandRow} aria-label="Reconciliation Platform home">
            <span className={styles.brandLogo}>R</span>
            <span className={styles.brandText}>Reconciliation</span>
          </Link>
          <button
            type="button"
            className={styles.collapseBtn}
            onClick={() => setPrefExpanded((v) => !v)}
            aria-label={expanded ? "Collapse sidebar" : "Expand sidebar"}
            aria-expanded={expanded}
            title={expanded ? "Collapse sidebar" : "Expand sidebar"}
          >
            <FiSidebar />
          </button>
          <button
            type="button"
            className={styles.mobileCloseBtn}
            onClick={() => setMobileOpen(false)}
            aria-label="Close navigation menu"
          >
            <FiX />
          </button>
        </div>

        <nav className={styles.navMain} aria-label="Sections">
          {navItems.map((it) => (
            <div key={it.key} className={styles.navGroup}>
              <NavItem
                to={it.to}
                icon={it.icon}
                label={it.label}
                active={activeKey === it.key}
              />
              {/*
                Wizard step navigator is contextual to the Reconciliation
                Engine: it renders indented directly beneath that nav item
                while on a wizard route, rather than as a page-level rail.
              */}
              {it.key === "reconciliation" && isWizard && (
                <div className={styles.contextNav}>
                  <WizardSidebarNav collapsed={!expanded} />
                </div>
              )}
            </div>
          ))}
        </nav>
      </aside>

      <main className={styles.main}>
        <div className={styles.mainInner}>{children}</div>
      </main>
    </div>
  );
}

export default AppLayout;
