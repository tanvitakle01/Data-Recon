import * as React from "react";
import { cn } from "../../lib/utils";

export interface PageHeroProps {
  /** Main heading shown in white, display weight. */
  title: React.ReactNode;
  /** Optional supporting line under the title. */
  subtitle?: React.ReactNode;
  /** Optional leading icon, rendered inside a frosted rounded tile. */
  icon?: React.ReactNode;
  /** Optional content pinned to the top-right (badges, scope chips, actions). */
  aside?: React.ReactNode;
  /** Extra content rendered below the title block (filters, tabs, stats…). */
  children?: React.ReactNode;
  className?: string;
}

/**
 * PageHero — the dark, gradient "hero title" banner used at the top of an app
 * screen. Shared across the Cone suite so every screen's header looks the same;
 * restyle here and all consumers update.
 */
export const PageHero: React.FC<PageHeroProps> = ({
  title,
  subtitle,
  icon,
  aside,
  children,
  className,
}) => {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-[var(--bcone-radius-lg)]",
        "bg-gradient-to-br from-[var(--bcone-black)] via-[#0f3138] to-[var(--bcone-teal)]",
        "px-[var(--bcone-spacing-8)] py-[var(--bcone-spacing-6)]",
        "shadow-[var(--bcone-shadow-md)]",
        className
      )}
    >
      {/* Subtle glow accent in the top-right, like the SDLC hero. */}
      <div
        aria-hidden
        className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-[var(--bcone-teal)]/20 blur-3xl"
      />

      <div className="relative flex items-start gap-[var(--bcone-spacing-4)]">
        {icon && (
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[var(--bcone-radius-md)] bg-white/10 text-white ring-1 ring-white/15 backdrop-blur-sm">
            {icon}
          </div>
        )}

        <div className="min-w-0 flex-1">
          <h1 className="text-2xl font-black leading-tight text-white">
            {title}
          </h1>
          {subtitle && (
            <p className="mt-1 max-w-3xl text-sm text-white/70">{subtitle}</p>
          )}
        </div>

        {aside && <div className="shrink-0 text-right text-white">{aside}</div>}
      </div>

      {children && <div className="relative mt-[var(--bcone-spacing-6)]">{children}</div>}
    </div>
  );
};
