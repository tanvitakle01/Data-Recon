import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { FiHome, FiLayers, FiBarChart2, FiDatabase, FiSettings } from "react-icons/fi";
import styles from "./appLayout.module.css";

function SidebarItem({
  to,
  icon: Icon,
  label,
  expanded,
  collapsedHint,
  active,
}) {
  return (
    <Link
      to={to}
      className={`${styles.item} ${active ? styles.itemActive : ""}`}
      title={collapsedHint}
    >
      <div className={styles.itemIconWrap}>
        <Icon className={styles.itemIcon} />
      </div>
      {expanded && <div className={styles.itemLabel}>{label}</div>}
    </Link>
  );
}

function AppLayout({ children }) {
  const location = useLocation();
  const [expanded, setExpanded] = useState(true);
  const [mobileCollapsed, setMobileCollapsed] = useState(true);

  const activeKey = useMemo(() => {
    const p = location.pathname;
    if (p.startsWith("/reconciliation")) return "reconciliation";
    if (p.startsWith("/insights/history")) return "insights";
    if (p.startsWith("/insights")) return "insights";
    if (p.startsWith("/data-sources")) return "data-sources";
    if (p.startsWith("/settings")) return "settings";
    return "home";
  }, [location.pathname]);

  useEffect(() => {
    // close mobile drawer on navigation
    setMobileCollapsed(true);

  }, [location.pathname]);

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

  return (
    <div className={styles.shell}>
      <aside
        className={`${styles.sidebar} ${expanded ? styles.sidebarExpanded : styles.sidebarCollapsed} ${
          mobileCollapsed ? styles.sidebarMobileCollapsed : styles.sidebarMobileOpen
        }`}
      >
        <div className={styles.sidebarTop}>
          <div className={styles.brandRow}>
            <div className={styles.brandLogo}>⚡</div>
            {expanded && <div className={styles.brandText}>Reconciliation Platform</div>}
          </div>

          <button
            type="button"
            className={styles.collapseBtn}
            onClick={() => setExpanded((v) => !v)}
            aria-label="Toggle sidebar"
          >
            {expanded ? "⟨" : "⟩"}
          </button>
        </div>

        <nav className={styles.nav}>
          {navItems.map((it) => (
            <SidebarItem
              key={it.key}
              to={it.to}
              icon={it.icon}
              label={it.label}
              expanded={expanded}
              collapsedHint={it.label}
              active={activeKey === it.key}
            />
          ))}
        </nav>

        <div className={styles.sidebarBottom}>
          <div className={styles.sidebarHint}>
            {expanded ? "Enterprise UI" : ""}
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

