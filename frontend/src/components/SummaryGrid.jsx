import PropTypes from "prop-types";
import MetricCard from "./MetricCard";

function SummaryGrid({ metrics }) {
  return (
    <div className="recon-summary-grid" role="group" aria-label="Summary metrics">
      {metrics.map((m) => (
        <MetricCard key={m.label} metric={m} />
      ))}
    </div>
  );
}


SummaryGrid.propTypes = {
  metrics: PropTypes.arrayOf(
    PropTypes.shape({
      label: PropTypes.string.isRequired,
      value: PropTypes.number.isRequired,
    }),
  ).isRequired,
};

export default SummaryGrid;

