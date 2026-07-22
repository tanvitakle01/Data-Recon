import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-[var(--bcone-radius-pill)] px-2.5 py-0.5 text-xs font-bold transition-colors",
  {
    variants: {
      variant: {
        success: "bg-[var(--bcone-green)]/15 text-[#1a6b3a] border border-[var(--bcone-green)]/30",
        warning: "bg-[var(--bcone-orange)]/15 text-[var(--bcone-orange)] border border-[var(--bcone-orange)]/30",
        error: "bg-[var(--bcone-red)]/15 text-[var(--bcone-red)] border border-[var(--bcone-red)]/30",
        info: "bg-[var(--bcone-blue)]/15 text-[var(--bcone-blue)] border border-[var(--bcone-blue)]/30",
        default: "bg-[var(--bcone-gray)]/15 text-[var(--bcone-charcoal)] border border-[var(--bcone-gray)]/30",
        teal: "bg-[var(--bcone-teal)]/15 text-[var(--bcone-teal)] border border-[var(--bcone-teal)]/30",
        purple: "bg-[var(--bcone-purple)]/15 text-[var(--bcone-purple)] border border-[var(--bcone-purple)]/30",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {
  dot?: boolean;
}

export const Badge: React.FC<BadgeProps> = ({ className, variant, dot = false, children, ...props }) => (
  <span className={cn(badgeVariants({ variant }), className)} {...props}>
    {dot && (
      <span
        className="h-1.5 w-1.5 rounded-full bg-current"
        aria-hidden="true"
      />
    )}
    {children}
  </span>
);

Badge.displayName = "Badge";

export { badgeVariants };
