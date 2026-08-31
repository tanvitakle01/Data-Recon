import PropTypes from "prop-types";
import styles from "./callout.module.css";

const TONE_LABEL = {
  info: "Note",
  scope: "Known limitation",
  medium: "Planned",
};

// Reuses the app's canonical .status-badge tones rather than inventing new
// callout colors — "info" for general asides, "scope" (already the neutral/
// boundary-of-the-system semantic) for known limitations, "medium" (already
// the amber confidence tier) for planned-but-not-built behavior.
function Callout({ tone = "info", title, children }) {
  return (
    <div className={styles.callout}>
      <span className={`status-badge status-badge--${tone}`}>
        <span className="status-badge__dot" />
        {title || TONE_LABEL[tone]}
      </span>
      <div className={styles.body}>{children}</div>
    </div>
  );
}

Callout.propTypes = {
  tone: PropTypes.oneOf(["info", "scope", "medium"]),
  title: PropTypes.string,
  children: PropTypes.node,
};

export default Callout;
