import * as React from "react";
import {
  AlertCircle,
  CheckCircle,
  Info,
  AlertTriangle,
  X,
} from "lucide-react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";

const alertVariants = cva(
  "flex items-start gap-3 rounded-[var(--bcone-radius-md)] border p-4 text-sm",
  {
    variants: {
      variant: {
        success:
          "bg-[var(--bcone-green)]/10 border-[var(--bcone-green)]/30 text-[#1a6b3a]",
        error:
          "bg-[var(--bcone-red)]/10 border-[var(--bcone-red)]/30 text-[var(--bcone-red)]",
        warning:
          "bg-[var(--bcone-orange)]/10 border-[var(--bcone-orange)]/30 text-[var(--bcone-orange)]",
        info: "bg-[var(--bcone-teal)]/10 border-[var(--bcone-teal)]/30 text-[var(--bcone-teal)]",
      },
    },
    defaultVariants: { variant: "info" },
  }
);

const ICONS = {
  success: CheckCircle,
  error: AlertCircle,
  warning: AlertTriangle,
  info: Info,
} as const;

export interface AlertProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof alertVariants> {
  title?: string;
  onDismiss?: () => void;
}

export const Alert: React.FC<AlertProps> = ({
  className,
  variant = "info",
  title,
  children,
  onDismiss,
  ...props
}) => {
  const Icon = ICONS[variant ?? "info"];
  return (
    <div
      className={cn(alertVariants({ variant }), className)}
      role="alert"
      {...props}
    >
      <Icon className="mt-0.5 h-4 w-4 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        {title && <p className="font-bold mb-0.5">{title}</p>}
        {children && <div className="leading-relaxed">{children}</div>}
      </div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="flex-shrink-0 opacity-60 hover:opacity-100 transition-opacity"
          aria-label="Dismiss"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
};
Alert.displayName = "Alert";
