import * as React from "react";
import { cn } from "../../lib/utils";

export interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Render as a circle (e.g. avatar placeholder). */
  circle?: boolean;
}

/**
 * Animated loading placeholder. Size it with utility classes, e.g.
 * `<Skeleton className="h-4 w-32" />`.
 */
export const Skeleton: React.FC<SkeletonProps> = ({
  circle = false,
  className,
  ...props
}) => (
  <div
    aria-hidden="true"
    className={cn(
      "animate-pulse bg-[var(--bcone-gray)]/15",
      circle ? "rounded-full" : "rounded-[var(--bcone-radius-md)]",
      className
    )}
    {...props}
  />
);
Skeleton.displayName = "Skeleton";
