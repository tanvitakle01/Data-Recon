import * as React from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "../../lib/utils";

export interface CollapsibleSectionProps {
  title: string;
  subtitle?: string;
  badge?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
  className?: string;
}

export const CollapsibleSection: React.FC<CollapsibleSectionProps> = ({
  title,
  subtitle,
  badge,
  defaultOpen = false,
  children,
  className,
}) => {
  const [open, setOpen] = React.useState(defaultOpen);

  return (
    <div
      className={cn(
        "overflow-hidden rounded-[var(--bcone-radius-md)] border border-[var(--bcone-gray)]/20",
        className
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between bg-[var(--bcone-charcoal)]/[0.03] px-4 py-3 text-left transition-colors hover:bg-[var(--bcone-teal)]/5"
      >
        <div className="flex min-w-0 items-center gap-3">
          {subtitle && (
            <span className="flex-shrink-0 text-xs font-black uppercase tracking-widest text-[var(--bcone-gray)]">
              {subtitle}
            </span>
          )}
          <span className="truncate font-bold text-[var(--bcone-charcoal)]">
            {title}
          </span>
        </div>
        <div className="ml-3 flex flex-shrink-0 items-center gap-2">
          {badge}
          {open ? (
            <ChevronUp className="h-4 w-4 text-[var(--bcone-gray)]" />
          ) : (
            <ChevronDown className="h-4 w-4 text-[var(--bcone-gray)]" />
          )}
        </div>
      </button>

      {open && (
        <div className="border-t border-[var(--bcone-gray)]/10 p-4">
          {children}
        </div>
      )}
    </div>
  );
};
CollapsibleSection.displayName = "CollapsibleSection";
