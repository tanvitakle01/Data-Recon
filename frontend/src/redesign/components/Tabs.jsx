import { cn } from "../lib/cn";

/**
 * Controlled tabs. `items`: [{ value, label, icon, badge }].
 * variant: "underline" (default) | "pill".
 */
export function Tabs({ items, value, onChange, variant = "underline", className }) {
  if (variant === "pill") {
    return (
      <div className={cn("inline-flex items-center gap-1 rounded-lg border border-line bg-surface-2 p-1", className)}>
        {items.map((it) => {
          const active = it.value === value;
          return (
            <button
              key={it.value}
              onClick={() => onChange?.(it.value)}
              className={cn(
                "inline-flex items-center gap-2 rounded-md px-3 h-8 text-[13px] font-medium transition-colors",
                active ? "bg-surface text-text shadow-e1" : "text-muted hover:text-text"
              )}
            >
              {it.icon}
              {it.label}
              {it.badge}
            </button>
          );
        })}
      </div>
    );
  }
  return (
    <div className={cn("flex items-center gap-6 border-b border-line", className)}>
      {items.map((it) => {
        const active = it.value === value;
        return (
          <button
            key={it.value}
            onClick={() => onChange?.(it.value)}
            className={cn(
              "relative -mb-px inline-flex items-center gap-2 py-3 text-sm font-medium transition-colors",
              active ? "text-text" : "text-muted hover:text-text-secondary"
            )}
          >
            {it.icon}
            {it.label}
            {it.badge}
            <span
              className={cn(
                "absolute inset-x-0 -bottom-px h-0.5 rounded-full transition-all duration-200 ease-[cubic-bezier(0.2,0,0,1)]",
                active ? "bg-accent opacity-100" : "opacity-0"
              )}
            />
          </button>
        );
      })}
    </div>
  );
}

export default Tabs;
