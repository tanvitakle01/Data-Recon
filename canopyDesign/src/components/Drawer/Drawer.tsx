import * as React from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { cn } from "../../lib/utils";

const SIDE = {
  left: "left-0 top-0 h-full",
  right: "right-0 top-0 h-full",
  top: "top-0 left-0 w-full",
  bottom: "bottom-0 left-0 w-full",
} as const;

const SLIDE = {
  left: "slide-in-from-left",
  right: "slide-in-from-right",
  top: "slide-in-from-top",
  bottom: "slide-in-from-bottom",
} as const;

const SIZE_X = { sm: "w-72", md: "w-96", lg: "w-[32rem]" } as const;
const SIZE_Y = { sm: "h-1/4", md: "h-1/3", lg: "h-1/2" } as const;

export interface DrawerProps {
  open?: boolean;
  onClose: () => void;
  side?: keyof typeof SIDE;
  size?: "sm" | "md" | "lg";
  title?: React.ReactNode;
  footer?: React.ReactNode;
  closeOnBackdrop?: boolean;
  closeOnEsc?: boolean;
  showClose?: boolean;
  className?: string;
  children?: React.ReactNode;
}

/** Slide-in panel anchored to a screen edge. Like Modal, but off-canvas. */
export const Drawer: React.FC<DrawerProps> = ({
  open = true,
  onClose,
  side = "right",
  size = "md",
  title,
  footer,
  closeOnBackdrop = true,
  closeOnEsc = true,
  showClose = true,
  className,
  children,
}) => {
  React.useEffect(() => {
    if (!open || !closeOnEsc) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, closeOnEsc, onClose]);

  if (!open) return null;

  const isHorizontal = side === "left" || side === "right";
  const sizeCls = isHorizontal ? SIZE_X[size] : SIZE_Y[size];
  const hasHeader = Boolean(title) || showClose;

  return createPortal(
    <div
      className="fixed inset-0 z-50"
      onClick={closeOnBackdrop ? onClose : undefined}
    >
      <div className="absolute inset-0 bg-[var(--bcone-black)]/60 backdrop-blur-sm animate-in fade-in" />

      <div
        className={cn(
          "absolute z-10 flex flex-col bg-white shadow-[var(--bcone-shadow-lg)] animate-in",
          SIDE[side],
          sizeCls,
          isHorizontal ? "max-w-[92vw]" : "max-h-[92vh]",
          SLIDE[side],
          className
        )}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        {hasHeader && (
          <div className="flex items-center justify-between gap-4 border-b border-[var(--bcone-gray)]/15 px-5 py-4">
            {title ? (
              <h2 className="text-base font-black text-[var(--bcone-charcoal)]">
                {title}
              </h2>
            ) : (
              <span />
            )}
            {showClose && (
              <button
                onClick={onClose}
                aria-label="Close"
                className="-mr-1 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-[var(--bcone-radius-md)] text-[var(--bcone-gray)] transition-colors hover:bg-[var(--bcone-gray)]/10 hover:text-[var(--bcone-charcoal)]"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>

        {footer && (
          <div className="flex items-center justify-end gap-3 border-t border-[var(--bcone-gray)]/15 px-5 py-4">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body
  );
};
Drawer.displayName = "Drawer";
