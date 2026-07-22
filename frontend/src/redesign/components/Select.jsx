import { ChevronDown } from "lucide-react";
import { cn } from "../lib/cn";

/** Lightweight styled native select (keyboard + a11y for free). */
export function Select({ className, invalid = false, children, ...props }) {
  return (
    <div className="relative">
      <select
        className={cn(
          "w-full appearance-none rounded-lg border bg-surface pl-3 pr-9 h-[34px] text-sm text-text",
          "outline-none transition-[border-color,box-shadow] duration-150",
          "focus:border-accent focus:ring-2 focus:ring-accent-ring disabled:opacity-50",
          invalid ? "border-missing-bd" : "border-line-2",
          className
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted" />
    </div>
  );
}

export default Select;
