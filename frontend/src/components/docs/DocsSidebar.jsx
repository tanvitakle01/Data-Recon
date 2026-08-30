import PropTypes from "prop-types";
import SECTIONS from "./docsSections";
import styles from "./docsSidebar.module.css";

function NavList({ activeId, onNavigate }) {
  return (
    <ul className={styles.list}>
      {SECTIONS.map((s) => (
        <li key={s.id} className={s.level === 3 ? styles.subItem : styles.item}>
          <a
            href={`#${s.id}`}
            className={`${styles.link} ${activeId === s.id ? styles.linkActive : ""}`}
            aria-current={activeId === s.id ? "true" : undefined}
            onClick={onNavigate}
          >
            {s.title}
          </a>
        </li>
      ))}
    </ul>
  );
}

NavList.propTypes = {
  activeId: PropTypes.string,
  onNavigate: PropTypes.func,
};

// Renders both a sticky desktop rail and a native <details> dropdown for
// narrow viewports — CSS (not JS) decides which is visible at a given width,
// and <details>/<summary> gives keyboard/screen-reader support for free.
function DocsSidebar({ activeId }) {
  return (
    <>
      <nav className={styles.desktop} aria-label="Architecture notes sections">
        <NavList activeId={activeId} />
      </nav>

      <details className={styles.mobile}>
        <summary className={styles.mobileSummary}>Contents</summary>
        <NavList activeId={activeId} onNavigate={(e) => e.currentTarget.closest("details")?.removeAttribute("open")} />
      </details>
    </>
  );
}

DocsSidebar.propTypes = {
  activeId: PropTypes.string,
};

export default DocsSidebar;
