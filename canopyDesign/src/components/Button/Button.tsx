import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-[var(--bcone-radius-sm)] text-sm font-bold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--bcone-teal)] focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary:
          "bg-[var(--bcone-teal)] text-white hover:bg-[var(--bcone-blue)] active:brightness-90",
        secondary:
          "bg-[var(--bcone-green)] text-[var(--bcone-black)] hover:bg-[var(--bcone-light-green)] active:brightness-90",
        ghost:
          "bg-transparent text-[var(--bcone-teal)] hover:bg-[var(--bcone-teal)]/10 border border-[var(--bcone-teal)]",
        destructive:
          "bg-[var(--bcone-red)] text-white hover:brightness-90 active:brightness-80",
        outline:
          "border border-[var(--bcone-gray)] bg-transparent text-[var(--bcone-charcoal)] hover:border-[var(--bcone-teal)] hover:text-[var(--bcone-teal)]",
      },
      size: {
        sm: "h-8 px-3 text-xs",
        md: "h-10 px-4",
        lg: "h-12 px-6 text-base",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "md",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, loading = false, children, disabled, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        disabled={disabled || loading}
        {...props}
      >
        {loading ? (
          <>
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4l3-3-3-3v4a8 8 0 100 16v-4l-3 3 3 3v-4a8 8 0 01-8-8z" />
            </svg>
            {children}
          </>
        ) : children}
      </Comp>
    );
  }
);

Button.displayName = "Button";

export { buttonVariants };
