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
import { BristleconeLogo } from "@bristlecone/canopy";
import { useTicketing } from "../ticketing/useTicketing";
import canopyPkg from "@bristlecone/canopy/package.json";
import styles from "./appLayout.module.css";

const SIDEBAR_STORAGE_KEY = "sidebar-expanded";
// Below this width the sidebar auto-collapses to the icon rail so data tables
// keep their room; above it, the user's saved preference wins.
const AUTO_COLLAPSE_WIDTH = 1024;

function NavItem({ to, icon: Icon, label, active, badge }) {
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
      {badge > 0 && <span className={styles.itemBadge}>{badge}</span>}
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

  // Tickets not yet Resolved/Closed — a real, live count (this ticketing
  // store is genuine app state, not mock data), shown on the nav badge the
  // same way the Enterprise UI mock shows an open-item count.
  const { tickets } = useTicketing();
  const openTicketCount = useMemo(
    () => tickets.filter((t) => t.status !== "Resolved" && t.status !== "Closed").length,
    [tickets],
  );

  // Ungrouped (mirrors the mock's own header identity, which already covers
  // "home") + the mock's Reconcile / Operate / Govern sections, applied to
  // this app's real, unchanged routes.
  const topNavItems = [{ key: "home", to: "/home", icon: FiHome, label: "Home" }];
  const navGroups = [
    {
      label: "Reconcile",
      items: [
        { key: "reconciliation", to: "/reconciliation", icon: FiLayers, label: "Reconciliation Engine" },
        { key: "library", to: "/library", icon: FiBookOpen, label: "Mapping Library" },
        { key: "insights", to: "/insights", icon: FiBarChart2, label: "Insights" },
      ],
    },
    {
      label: "Operate",
      items: [
        { key: "ticketing", to: "/ticketing", icon: FiClipboard, label: "Ticketing", badge: openTicketCount },
        { key: "data-sources", to: "/data-sources", icon: FiDatabase, label: "Data Sources" },
      ],
    },
    {
      label: "Govern",
      items: [{ key: "settings", to: "/settings", icon: FiSettings, label: "Settings" }],
    },
  ];

  return (
    <div className={styles.shell}>
      <header className={styles.topHeader}>
        <button
          type="button"
          className={styles.mobileMenuBtn}
          onClick={() => setMobileOpen(true)}
          aria-label="Open navigation menu"
          aria-expanded={mobileOpen}
        >
          <FiMenu />
        </button>
        <Link to="/home" className={styles.brandRow} aria-label="Data Reconciliation home">
          <BristleconeLogo size="sm" />
          <span className={styles.brandDivider} aria-hidden="true" />
          <span className={styles.brandText}>Data Reconciliation</span>
        </Link>
      </header>

      <div
        className={`${styles.backdrop} ${mobileOpen ? styles.backdropVisible : ""}`}
        onClick={() => setMobileOpen(false)}
        aria-hidden="true"
      />

      <div className={styles.body}>
        <aside
          className={`${styles.sidebar} ${expanded ? styles.sidebarExpanded : styles.sidebarCollapsed} ${
            mobileOpen ? styles.sidebarMobileOpen : ""
          }`}
          aria-label="Primary navigation"
        >
          <div className={styles.sidebarTop}>
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
            {topNavItems.map((it) => (
              <div key={it.key} className={styles.navGroup}>
                <NavItem to={it.to} icon={it.icon} label={it.label} active={activeKey === it.key} />
              </div>
            ))}

            {navGroups.map((group) => (
              <div key={group.label} className={styles.navSection}>
                <p className={styles.navSectionLabel}>{group.label}</p>
                {group.items.map((it) => (
                  <div key={it.key} className={styles.navGroup}>
                    <NavItem
                      to={it.to}
                      icon={it.icon}
                      label={it.label}
                      active={activeKey === it.key}
                      badge={it.badge}
                    />
                  </div>
                ))}
              </div>
            ))}
          </nav>

          <div className={styles.sidebarFooter}>
            <p className={styles.sidebarFooterText}>Canopy {canopyPkg.version}</p>
          </div>
        </aside>

        <main className={styles.main}>
          <div className={styles.mainInner}>{children}</div>
        </main>
      </div>
    </div>
  );
}

export default AppLayout;
