import * as React from "react";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { cn } from "../../lib/utils";

export interface KPICardProps {
  label: string;
  value: string | number;
  delta?: number;
  deltaLabel?: string;
  icon?: React.ReactNode;
  className?: string;
}

export const KPICard: React.FC<KPICardProps> = ({
  label,
  value,
  delta,
  deltaLabel,
  icon,
  className,
}) => {
  const deltaPositive = delta !== undefined && delta > 0;
  const deltaNegative = delta !== undefined && delta < 0;

  return (
    <div
      className={cn(
        "rounded-[var(--bcone-radius-md)] border border-[var(--bcone-gray)]/20 bg-white p-[var(--bcone-spacing-6)] shadow-[var(--bcone-shadow-sm)]",
        className
      )}
    >
      <div className="flex items-start justify-between">
        <p className="text-sm font-bold text-[var(--bcone-gray)] uppercase tracking-wide">
          {label}
        </p>
        {icon && (
          <span className="text-[var(--bcone-teal)] opacity-60">{icon}</span>
        )}
      </div>

      <p className="mt-2 text-3xl font-black text-[var(--bcone-charcoal)] leading-none">
        {value}
      </p>

      {delta !== undefined && (
        <div
          className={cn(
            "mt-2 inline-flex items-center gap-1 text-xs font-bold",
            deltaPositive && "text-[#1a6b3a]",
            deltaNegative && "text-[var(--bcone-red)]",
            !deltaPositive && !deltaNegative && "text-[var(--bcone-gray)]"
          )}
        >
          {deltaPositive ? (
            <TrendingUp className="h-3.5 w-3.5" />
          ) : deltaNegative ? (
            <TrendingDown className="h-3.5 w-3.5" />
          ) : (
            <Minus className="h-3.5 w-3.5" />
          )}
          <span>
            {delta > 0 ? "+" : ""}
            {delta}% {deltaLabel ?? "vs last period"}
          </span>
        </div>
      )}
    </div>
  );
};
