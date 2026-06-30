import PropTypes from "prop-types";
import Counter from "./Counter";

function MetricCard({ metric }) {
  return (
    <div className="recon-metric-card">
      <div className="recon-metric-label">{metric.label}</div>
      <div className="recon-metric-value">
        <Counter
          value={metric.value}
          fontSize={34}
          gap={2}
          textColor="#0F172A"
          fontWeight={700}
        />
      </div>
    </div>
  );
}

MetricCard.propTypes = {
  metric: PropTypes.shape({
    label: PropTypes.string.isRequired,
    value: PropTypes.number.isRequired,
  }).isRequired,
};

export default MetricCard;

