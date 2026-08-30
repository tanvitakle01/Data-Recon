import PropTypes from "prop-types";
import { FiArrowLeft, FiArrowRight, FiArrowUp } from "react-icons/fi";
import SECTIONS from "./docsSections";
import styles from "./sectionFooterNav.module.css";

// Previous/next links for one section, derived from the same SECTIONS list
// the sidebar renders — so a section can never point at a title that no
// longer matches its neighbor.
function SectionFooterNav({ id }) {
  const idx = SECTIONS.findIndex((s) => s.id === id);
  const prev = idx > 0 ? SECTIONS[idx - 1] : null;
  const next = idx >= 0 && idx < SECTIONS.length - 1 ? SECTIONS[idx + 1] : null;

  return (
    <div className={styles.wrap}>
      <div className={styles.side}>
        {prev && (
          <a href={`#${prev.id}`} className={styles.link}>
            <FiArrowLeft aria-hidden="true" />
            <span>
              <span className={styles.label}>Previous</span>
              {prev.title}
            </span>
          </a>
        )}
      </div>
      <a href="#top" className={styles.top}>
        <FiArrowUp aria-hidden="true" /> Back to top
      </a>
      <div className={`${styles.side} ${styles.sideRight}`}>
        {next && (
          <a href={`#${next.id}`} className={`${styles.link} ${styles.linkRight}`}>
            <span>
              <span className={styles.label}>Next</span>
              {next.title}
            </span>
            <FiArrowRight aria-hidden="true" />
          </a>
        )}
      </div>
    </div>
  );
}

SectionFooterNav.propTypes = {
  id: PropTypes.string.isRequired,
};

export default SectionFooterNav;
