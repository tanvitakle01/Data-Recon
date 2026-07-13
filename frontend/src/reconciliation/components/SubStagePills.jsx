// Non-interactive progress indicator for the progressive-disclosure card
// sequence within a single wizard step (e.g. Source/Target). Purely
// presentational — it does not drive navigation, only shows where the user
// is among the 2 (Excel/CSV) or 4 (SAP) cards for that step.
function SubStagePills({ stages, activeIndex }) {
  if (!stages || stages.length < 2) return null;

  return (
    <ol className="wizard-substage-pills">
      {stages.map((label, i) => {
        const state = i < activeIndex ? "done" : i === activeIndex ? "active" : "upcoming";
        return (
          <li key={label} className={`wizard-substage-pills__item is-${state}`}>
            <span className="wizard-substage-pills__marker">
              {state === "done" ? "✓" : i + 1}
            </span>
            <span className="wizard-substage-pills__label">{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

export default SubStagePills;
