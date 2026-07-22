import { Check } from "lucide-react";
import { cn } from "../lib/cn";

export function Toggle({ checked, onChange, disabled, label, className }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange?.(!checked)}
      className={cn("group inline-flex items-center gap-2.5 disabled:opacity-50", className)}
    >
      <span
        className={cn(
          "relative h-5 w-9 shrink-0 rounded-full transition-colors duration-200 ease-[cubic-bezier(0.2,0,0,1)]",
          checked ? "bg-accent" : "bg-line-3"
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow-e1 transition-transform duration-200 ease-[cubic-bezier(0.2,0,0,1)]",
            checked && "translate-x-4"
          )}
        />
      </span>
      {label && <span className="text-sm text-text-secondary">{label}</span>}
    </button>
  );
}

export function Checkbox({ checked, onChange, disabled, label, className }) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange?.(!checked)}
      className={cn("group inline-flex items-center gap-2 disabled:opacity-50", className)}
    >
      <span
        className={cn(
          "flex h-4 w-4 items-center justify-center rounded-[5px] border transition-colors",
          checked ? "bg-accent border-accent text-white" : "bg-surface border-line-3"
        )}
      >
        {checked && <Check className="h-3 w-3" strokeWidth={3} />}
      </span>
      {label && <span className="text-sm text-text-secondary">{label}</span>}
    </button>
  );
}

export default Toggle;
