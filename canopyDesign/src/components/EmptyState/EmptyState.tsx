import * as React from "react";
import { cn } from "../../lib/utils";

export interface EmptyStateProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  /** Icon shown above the title (e.g. a lucide icon element). */
  icon?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  /** Optional call-to-action (e.g. a Button). */
  action?: React.ReactNode;
}

/** Centered placeholder for "no data" / empty-list states. */
export const EmptyState: React.FC<EmptyStateProps> = ({
  icon,
  title,
  description,
  action,
  className,
  ...props
}) => (
  <div
    className={cn(
      "flex flex-col items-center justify-center px-6 py-10 text-center",
      className
    )}
    {...props}
  >
    {icon && (
      <div className="mb-3 text-[var(--bcone-gray)] opacity-40 [&_svg]:h-8 [&_svg]:w-8">
        {icon}
      </div>
    )}
    <p className="text-sm font-bold text-[var(--bcone-charcoal)]">{title}</p>
    {description && (
      <p className="mt-1 max-w-sm text-sm text-[var(--bcone-gray)]">{description}</p>
    )}
    {action && <div className="mt-4">{action}</div>}
  </div>
);
EmptyState.displayName = "EmptyState";
