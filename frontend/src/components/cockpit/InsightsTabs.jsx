const TABS = [
  { id: "executive", label: "Executive Summary" },
  { id: "detailed", label: "Detailed Insights" },
];

/**
 * Top-level tab strip for the Insights page. Underline-style switcher in the
 * same slate/blue palette as the rest of the cockpit, so it reads as part of
 * one design system rather than a bolted-on nav control.
 */
export default function InsightsTabs({ active, onChange }) {
  return (
    <div role="tablist" aria-label="Reconciliation analysis view" className="mb-6 flex items-center gap-1 border-b border-slate-200">
      {TABS.map((tab) => {
        const isActive = tab.id === active;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(tab.id)}
            className={`relative -mb-px px-4 py-3 text-sm font-extrabold transition-colors duration-150 ${
              isActive ? "text-slate-900" : "text-slate-400 hover:text-slate-600"
            }`}
          >
            {tab.label}
            <span
              className={`absolute inset-x-3 bottom-0 h-[2.5px] rounded-full transition-opacity duration-150 ${
                isActive ? "opacity-100 bg-blue-600" : "opacity-0"
              }`}
            />
          </button>
        );
      })}
    </div>
  );
}
