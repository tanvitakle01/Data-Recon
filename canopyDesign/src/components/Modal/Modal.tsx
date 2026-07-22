import * as React from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { cn } from "../../lib/utils";

const SIZES = {
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-lg",
  xl: "max-w-2xl",
} as const;

export interface ModalProps {
  /** Whether the modal is shown. Defaults to true so `{cond && <Modal/>}` works. */
  open?: boolean;
  onClose: () => void;
  title?: React.ReactNode;
  description?: React.ReactNode;
  /** Footer content (e.g. action buttons), right-aligned in a bordered bar. */
  footer?: React.ReactNode;
  size?: keyof typeof SIZES;
  /** Close when the backdrop is clicked. Default true. */
  closeOnBackdrop?: boolean;
  /** Close when Escape is pressed. Default true. */
  closeOnEsc?: boolean;
  /** Show the ✕ button in the header. Default true. */
  showClose?: boolean;
  className?: string;
  bodyClassName?: string;
  children?: React.ReactNode;
}

/**
 * Generic modal/dialog shell: backdrop + centered panel + optional titled header,
 * scrollable body, and footer. For yes/no confirmations prefer `ConfirmDialog`.
 */
export const Modal: React.FC<ModalProps> = ({
  open = true,
  onClose,
  title,
  description,
  footer,
  size = "md",
  closeOnBackdrop = true,
  closeOnEsc = true,
  showClose = true,
  className,
  bodyClassName,
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

  const hasHeader = Boolean(title) || showClose;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={closeOnBackdrop ? onClose : undefined}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-[var(--bcone-black)]/60 backdrop-blur-sm animate-in fade-in" />

      {/* Panel */}
      <div
        className={cn(
          "relative z-10 flex max-h-[85vh] w-full flex-col overflow-hidden rounded-[var(--bcone-radius-lg)] bg-white shadow-[var(--bcone-shadow-lg)]",
          SIZES[size],
          className
        )}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        {hasHeader && (
          <div className="flex items-start justify-between gap-4 border-b border-[var(--bcone-gray)]/15 px-6 py-4">
            <div className="min-w-0">
              {title && (
                <h2 className="text-lg font-black leading-tight text-[var(--bcone-charcoal)]">
                  {title}
                </h2>
              )}
              {description && (
                <p className="mt-1 text-sm text-[var(--bcone-gray)]">{description}</p>
              )}
            </div>
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

        <div className={cn("flex-1 overflow-y-auto px-6 py-5", bodyClassName)}>
          {children}
        </div>

        {footer && (
          <div className="flex items-center justify-end gap-3 border-t border-[var(--bcone-gray)]/15 px-6 py-4">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body
  );
};
Modal.displayName = "Modal";
