import * as React from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "../../lib/utils";

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface SelectProps
  extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "children"> {
  label?: string;
  error?: string;
  hint?: string;
  options: SelectOption[];
  placeholder?: string;
}

export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  (
    { className, label, error, hint, id, options, placeholder, ...props },
    ref
  ) => {
    const selectId = id ?? label?.toLowerCase().replace(/\s+/g, "-");
    return (
      <div className="flex flex-col gap-1">
        {label && (
          <label
            htmlFor={selectId}
            className="text-sm font-bold text-[var(--bcone-charcoal)]"
          >
            {label}
          </label>
        )}
        <div className="relative">
          <select
            ref={ref}
            id={selectId}
            className={cn(
              "h-10 w-full appearance-none rounded-[var(--bcone-radius-sm)] border bg-white px-3 pr-8 text-sm text-[var(--bcone-charcoal)] transition-colors",
              "focus:outline-none focus:ring-2 focus:ring-[var(--bcone-teal)] focus:border-transparent",
              "disabled:cursor-not-allowed disabled:opacity-50",
              error
                ? "border-[var(--bcone-red)] focus:ring-[var(--bcone-red)]"
                : "border-[var(--bcone-gray)]",
              className
            )}
            {...props}
          >
            {placeholder && (
              <option value="" disabled>
                {placeholder}
              </option>
            )}
            {options.map((opt) => (
              <option key={opt.value} value={opt.value} disabled={opt.disabled}>
                {opt.label}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--bcone-gray)]" />
        </div>
        {error && (
          <p className="text-xs text-[var(--bcone-red)]" role="alert">
            {error}
          </p>
        )}
        {hint && !error && (
          <p className="text-xs text-[var(--bcone-gray)]">{hint}</p>
        )}
      </div>
    );
  }
);
Select.displayName = "Select";
