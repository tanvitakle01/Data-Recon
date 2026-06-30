import PropTypes from "prop-types";

function BorderGlow({ children, colors = ["#2563EB", "#0EA5E9", "#38BDF8"] }) {
  return (
    <div
      className="recon-border-glow"
      style={{ ["--recon-glow-colors"]: colors.join(",") }}
    >
      <div className="recon-border-glow-inner">{children}</div>
    </div>
  );
}

BorderGlow.propTypes = {
  children: PropTypes.node.isRequired,
  colors: PropTypes.arrayOf(PropTypes.string),
};

export default BorderGlow;

