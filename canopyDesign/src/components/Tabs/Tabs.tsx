import * as React from "react";
import { cn } from "../../lib/utils";

export interface TabItem {
  id: string;
  label: React.ReactNode;
  icon?: React.ReactNode;
  disabled?: boolean;
}

export interface TabsProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "onChange"> {
  items: TabItem[];
  /** The id of the active tab (controlled). */
  value: string;
  onChange: (id: string) => void;
  variant?: "underline" | "pills";
  className?: string;
}

/**
 * Controlled tab bar. Renders the tab strip only — the caller renders the active
 * panel based on `value`. Two looks: `underline` (default) and `pills`.
 */
export const Tabs: React.FC<TabsProps> = ({
  items,
  value,
  onChange,
  variant = "underline",
  className,
  ...props
}) => {
  const isPills = variant === "pills";

  return (
    <div
      role="tablist"
      className={cn(
        isPills
          ? "flex flex-wrap gap-1"
          : "flex gap-0.5 overflow-x-auto border-b border-[var(--bcone-gray)]/20",
        className
      )}
      {...props}
    >
      {items.map((t) => {
        const active = t.id === value;
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={active}
            disabled={t.disabled}
            onClick={() => onChange(t.id)}
            className={cn(
              "flex items-center gap-1.5 whitespace-nowrap text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40",
              isPills
                ? cn(
                    "rounded-[var(--bcone-radius-md)] px-3 py-1.5",
                    active
                      ? "bg-[var(--bcone-teal)] text-white"
                      : "text-[var(--bcone-gray)] hover:bg-[var(--bcone-gray)]/10 hover:text-[var(--bcone-charcoal)]"
                  )
                : cn(
                    "-mb-px border-b-2 px-3 py-2.5",
                    active
                      ? "border-[var(--bcone-teal)] text-[var(--bcone-teal)]"
                      : "border-transparent text-[var(--bcone-gray)] hover:text-[var(--bcone-charcoal)]"
                  )
            )}
          >
            {t.icon}
            {t.label}
          </button>
        );
      })}
    </div>
  );
};
Tabs.displayName = "Tabs";
