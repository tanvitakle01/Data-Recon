import * as React from "react";
import { cn } from "../../lib/utils";

const SIZES = {
  sm: "h-4 w-4 border-2",
  md: "h-5 w-5 border-2",
  lg: "h-8 w-8 border-[3px]",
} as const;

export interface SpinnerProps extends React.HTMLAttributes<HTMLDivElement> {
  size?: keyof typeof SIZES;
  /** Accessible label announced to screen readers. */
  label?: string;
}

/** Indeterminate loading spinner. */
export const Spinner: React.FC<SpinnerProps> = ({
  size = "md",
  label = "Loading",
  className,
  ...props
}) => (
  <div
    role="status"
    aria-label={label}
    className={cn(
      "inline-block animate-spin rounded-full border-[var(--bcone-teal)] border-t-transparent",
      SIZES[size],
      className
    )}
    {...props}
  />
);
Spinner.displayName = "Spinner";
