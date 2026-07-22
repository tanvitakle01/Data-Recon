import * as React from "react";
import * as RadixTooltip from "@radix-ui/react-tooltip";
import { cn } from "../../lib/utils";

export interface TooltipProps {
  /** The hover/focus content of the tooltip. */
  content: React.ReactNode;
  /** The trigger element. */
  children: React.ReactNode;
  side?: "top" | "right" | "bottom" | "left";
  align?: "start" | "center" | "end";
  delayDuration?: number;
  /** Set false to render children without a tooltip (e.g. when content is empty). */
  open?: boolean;
  className?: string;
}

/**
 * Lightweight tooltip wrapper around Radix. Wrap any focusable/hoverable element:
 * `<Tooltip content="Copy"><button>…</button></Tooltip>`.
 */
export const Tooltip: React.FC<TooltipProps> = ({
  content,
  children,
  side = "top",
  align = "center",
  delayDuration = 300,
  className,
}) => {
  if (content == null || content === "") return <>{children}</>;
  return (
    <RadixTooltip.Provider delayDuration={delayDuration}>
      <RadixTooltip.Root>
        <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
        <RadixTooltip.Portal>
          <RadixTooltip.Content
            side={side}
            align={align}
            sideOffset={6}
            className={cn(
              "z-50 max-w-xs rounded-[var(--bcone-radius-md)] bg-[var(--bcone-charcoal)] px-2.5 py-1.5 text-xs font-medium text-white shadow-[var(--bcone-shadow-md)] animate-in fade-in",
              className
            )}
          >
            {content}
            <RadixTooltip.Arrow className="fill-[var(--bcone-charcoal)]" />
          </RadixTooltip.Content>
        </RadixTooltip.Portal>
      </RadixTooltip.Root>
    </RadixTooltip.Provider>
  );
};
Tooltip.displayName = "Tooltip";
