import PropTypes from "prop-types";

function GradientText({ colors, animationSpeed = 8, direction = "horizontal", children }) {
  const className = "recon-gradient-text";

  const style = {
    // CSS variables for gradient
    ["--recon-grad-colors"]: colors.join(","),
    ["--recon-grad-speed"]: `${animationSpeed}`,
    ["--recon-grad-dir"]: direction,
  };

  return (
    <span className={className} style={style}>
      {children}
    </span>
  );
}

GradientText.propTypes = {
  colors: PropTypes.arrayOf(PropTypes.string).isRequired,
  animationSpeed: PropTypes.number,
  direction: PropTypes.oneOf(["horizontal", "vertical"]),
  children: PropTypes.node.isRequired,
};

export default GradientText;

