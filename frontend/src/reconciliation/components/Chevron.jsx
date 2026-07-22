// Small rotating chevron used by the Mapping Review accordions. Rotates from
// pointing-right (collapsed) to pointing-down (open); the rotation is animated
// in CSS via the `is-open` state on the parent, so this stays presentational.
function Chevron({ open = false, className = "" }) {
  return (
    <svg
      className={`mr-chev${open ? " is-open" : ""} ${className}`.trim()}
      viewBox="0 0 16 16"
      width="14"
      height="14"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M6 4l4 4-4 4" />
    </svg>
  );
}

export default Chevron;
