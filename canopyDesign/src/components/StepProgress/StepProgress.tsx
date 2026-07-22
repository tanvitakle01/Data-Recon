import * as React from "react";
import { Check, X, Loader } from "lucide-react";
import { cn } from "../../lib/utils";

export type StepStatus = "pending" | "active" | "complete" | "error";

export interface Step {
  label: string;
  status: StepStatus;
  detail?: string;
}

export interface StepProgressProps {
  steps: Step[];
  className?: string;
}

export const StepProgress: React.FC<StepProgressProps> = ({
  steps,
  className,
}) => {
  return (
    <div className={cn("space-y-1.5", className)}>
      {steps.map((step, i) => (
        <div key={i} className="flex items-center gap-3">
          {/* Step icon */}
          <div
            className={cn(
              "flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full border-2 text-xs font-black transition-all duration-200",
              step.status === "complete" &&
                "border-[var(--bcone-green)] bg-[var(--bcone-green)] text-white",
              step.status === "active" &&
                "border-[var(--bcone-teal)] bg-[var(--bcone-teal)] text-white",
              step.status === "error" &&
                "border-[var(--bcone-red)] bg-[var(--bcone-red)] text-white",
              step.status === "pending" &&
                "border-[var(--bcone-gray)]/30 bg-white text-[var(--bcone-gray)]"
            )}
          >
            {step.status === "complete" && <Check className="h-3.5 w-3.5" />}
            {step.status === "error" && <X className="h-3.5 w-3.5" />}
            {step.status === "active" && (
              <Loader className="h-3.5 w-3.5 animate-spin" />
            )}
            {step.status === "pending" && <span>{i + 1}</span>}
          </div>

          {/* Label + detail */}
          <div className="flex-1 min-w-0">
            <span
              className={cn(
                "text-sm font-bold leading-none",
                step.status === "complete" && "text-[var(--bcone-charcoal)]",
                step.status === "active" && "text-[var(--bcone-teal)]",
                step.status === "error" && "text-[var(--bcone-red)]",
                step.status === "pending" && "text-[var(--bcone-gray)]"
              )}
            >
              {step.label}
            </span>
            {step.detail && (
              <p className="text-xs text-[var(--bcone-gray)] mt-0.5 truncate">
                {step.detail}
              </p>
            )}
          </div>

          {step.status === "active" && (
            <span className="flex-shrink-0 text-xs font-bold text-[var(--bcone-teal)] animate-pulse">
              Running…
            </span>
          )}
        </div>
      ))}
    </div>
  );
};
StepProgress.displayName = "StepProgress";
