import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  FiHome,
  FiLayers,
  FiBarChart2,
  FiDatabase,
  FiSettings,
  FiChevronLeft,
  FiChevronRight,
  FiMenu,
  FiX,
  FiClipboard,
} from "react-icons/fi";
import styles from "./appLayout.module.css";

const SIDEBAR_STORAGE_KEY = "sidebar-expanded";

function SidebarItem({ to, icon: Icon, label, active }) {
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
  const [expanded, setExpanded] = useState(() => {
    if (typeof window === "undefined") return true;
    const saved = window.localStorage.getItem(SIDEBAR_STORAGE_KEY);
    return saved === null ? true : saved === "true";
  });
  const [mobileOpen, setMobileOpen] = useState(false);

  const activeKey = useMemo(() => {
    const p = location.pathname;
    if (p.startsWith("/reconciliation")) return "reconciliation";
    if (p.startsWith("/insights/history")) return "insights";
    if (p.startsWith("/insights")) return "insights";
    if (p.startsWith("/ticketing")) return "ticketing";
    if (p.startsWith("/data-sources")) return "data-sources";
    if (p.startsWith("/settings")) return "settings";
    return "home";
  }, [location.pathname]);

  useEffect(() => {
    // close mobile drawer on navigation
    setMobileOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(expanded));
  }, [expanded]);

  useEffect(() => {
    if (!mobileOpen) return undefined;
    const onKeyDown = (e) => {
      if (e.key === "Escape") setMobileOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [mobileOpen]);

  // Inside the Reconciliation Engine the wizard becomes a dedicated full-width
  // workspace: the vertical sidebar is replaced by a slim top bar so the
  // source/target/mapping/rules/review/results content gets the whole page.
  const isWizard = activeKey === "reconciliation";

  const navItems = [
    {
      key: "home",
      to: "/home",
      icon: FiHome,
      label: "Home",
    },
    {
      key: "reconciliation",
      to: "/reconciliation",
      icon: FiLayers,
      label: "Reconciliation Engine",
    },
    {
      key: "insights",
      to: "/insights",
      icon: FiBarChart2,
      label: "Insights",
    },
    {
      key: "ticketing",
      to: "/ticketing",
      icon: FiClipboard,
      label: "Ticketing",
    },
    {
      key: "data-sources",
      to: "/data-sources",
      icon: FiDatabase,
      label: "Data Sources",
    },
    {
      key: "settings",
      to: "/settings",
      icon: FiSettings,
      label: "Settings",
    },
  ];

  if (isWizard) {
    return (
      <div className={styles.wizardShell}>
        <header className={styles.wizardTopbar}>
          <div className={styles.wizardCrumbs}>
            <Link to="/home" className={styles.wizardBrand} aria-label="Home">
              <span className={styles.brandLogo}>⚡</span>
            </Link>
            <span className={styles.wizardCrumbSep}>›</span>
            <span className={styles.wizardCrumbActive}>Reconciliation Engine</span>
          </div>
          <nav className={styles.wizardNav} aria-label="Primary navigation">
            {navItems
              .filter((it) => it.key !== "reconciliation")
              .map((it) => (
                <Link
                  key={it.key}
                  to={it.to}
                  className={styles.wizardNavItem}
                  aria-label={it.label}
                  data-tooltip={it.label}
                >
                  <it.icon className={styles.itemIcon} />
                  <span className={styles.wizardNavLabel}>{it.label}</span>
                </Link>
              ))}
          </nav>
        </header>
        <main className={styles.main}>
          <div className={`${styles.mainInner} ${styles.mainInnerWizard}`}>{children}</div>
        </main>
      </div>
    );
  }

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
          mobileOpen ? styles.sidebarMobileOpen : styles.sidebarMobileCollapsed
        }`}
        aria-label="Primary navigation"
      >
        <button
          type="button"
          className={styles.collapseBtn}
          onClick={() => setExpanded((v) => !v)}
          aria-label={expanded ? "Collapse sidebar" : "Expand sidebar"}
          aria-expanded={expanded}
        >
          {expanded ? <FiChevronLeft /> : <FiChevronRight />}
        </button>

        <div className={styles.sidebarTop}>
          <div className={styles.brandRow}>
            <div className={styles.brandLogo}>⚡</div>
            <div className={styles.brandText}>Reconciliation Platform</div>
          </div>

          <button
            type="button"
            className={styles.mobileCloseBtn}
            onClick={() => setMobileOpen(false)}
            aria-label="Close navigation menu"
          >
            <FiX />
          </button>
        </div>

        <nav className={styles.nav} aria-label="Main">
          {navItems.map((it) => (
            <SidebarItem
              key={it.key}
              to={it.to}
              icon={it.icon}
              label={it.label}
              active={activeKey === it.key}
            />
          ))}
        </nav>

        <div className={styles.sidebarBottom}>
          <div className={styles.sidebarHint}>
            <span className={styles.hintDot} />
            <span className={styles.hintText}>Enterprise UI</span>
          </div>
        </div>
      </aside>

      <main className={styles.main}>
        <div className={styles.mainInner}>{children}</div>
      </main>
    </div>
  );
}

export default AppLayout;

