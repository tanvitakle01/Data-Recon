import { Check, Lock } from "lucide-react";
import { cn } from "../lib/cn";

/**
 * Vertical wizard step navigator.
 * steps: [{ key, label, caption?, status }]
 *   status: "complete" | "current" | "available" | "locked"
 */
export function Stepper({ steps, onStepClick, compact = false, className }) {
  return (
    <ol className={cn("flex flex-col", className)}>
      {steps.map((s, i) => {
        const last = i === steps.length - 1;
        const clickable = (s.status === "complete" || s.status === "available" || s.status === "current") && onStepClick;
        return (
          <li key={s.key} className="relative">
            {!last && (
              <span
                className={cn(
                  "absolute left-[13px] top-7 h-[calc(100%-1.25rem)] w-px",
                  s.status === "complete" ? "bg-accent/40" : "bg-line-2"
                )}
              />
            )}
            <button
              disabled={!clickable}
              onClick={clickable ? () => onStepClick(s, i) : undefined}
              className={cn(
                "group relative flex w-full items-center gap-3 rounded-lg py-1.5 pl-1 pr-2 text-left transition-colors",
                clickable && "hover:bg-surface-2",
                s.status === "locked" && "cursor-default"
              )}
            >
              <span
                className={cn(
                  "z-10 flex h-[27px] w-[27px] shrink-0 items-center justify-center rounded-full border text-[12px] font-semibold transition-colors",
                  s.status === "complete" && "border-accent bg-accent text-on-accent",
                  s.status === "current" && "border-accent bg-accent-tint text-accent-text ring-4 ring-accent-ring/40",
                  s.status === "available" && "border-line-2 bg-surface text-muted group-hover:border-line-3",
                  s.status === "locked" && "border-line bg-surface-2 text-faint"
                )}
              >
                {s.status === "complete" ? (
                  <Check className="h-3.5 w-3.5" strokeWidth={3} />
                ) : s.status === "locked" ? (
                  <Lock className="h-3 w-3" />
                ) : (
                  i + 1
                )}
              </span>
              {!compact && (
                <span className="min-w-0">
                  <span
                    className={cn(
                      "block truncate text-[13px] font-medium",
                      s.status === "current" ? "text-text" : s.status === "locked" ? "text-faint" : "text-text-secondary"
                    )}
                  >
                    {s.label}
                  </span>
                  {s.caption && <span className="block truncate text-[11px] text-muted">{s.caption}</span>}
                </span>
              )}
            </button>
          </li>
        );
      })}
    </ol>
  );
}

export default Stepper;
