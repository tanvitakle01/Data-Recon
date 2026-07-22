import { cn } from "../lib/cn";

/**
 * Compact segmented control. options: [{ value, label, icon }].
 * `accentActive` tints the active segment with the accent (used for Key vs Compare).
 */
export function SegmentedControl({ options, value, onChange, size = "md", accentActive = false, className }) {
  const h = size === "sm" ? "h-7" : "h-8";
  const txt = size === "sm" ? "text-[12px]" : "text-[13px]";
  return (
    <div className={cn("inline-flex items-center gap-0.5 rounded-lg border border-line bg-surface-2 p-0.5", className)}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            onClick={() => onChange?.(o.value)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-2.5 font-medium transition-colors",
              h, txt,
              active
                ? accentActive
                  ? "bg-accent text-on-accent shadow-e1"
                  : "bg-surface text-text shadow-e1"
                : "text-muted hover:text-text"
            )}
          >
            {o.icon}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export default SegmentedControl;
