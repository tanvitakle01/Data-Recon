import * as React from "react";
import { createPortal } from "react-dom";
import { AlertTriangle } from "lucide-react";
import { Button } from "../Button";
import { cn } from "../../lib/utils";

export interface ConfirmDialogProps {
  isOpen: boolean;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  variant?: "default" | "destructive";
  onConfirm: () => void;
  onCancel: () => void;
  className?: string;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  isOpen,
  title,
  message,
  confirmText = "Confirm",
  cancelText = "Cancel",
  variant = "default",
  onConfirm,
  onCancel,
  className,
}) => {
  // Keyboard: Escape closes, Enter confirms
  React.useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
      if (e.key === "Enter") onConfirm();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, onCancel, onConfirm]);

  if (!isOpen) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={onCancel}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-[var(--bcone-black)]/60 backdrop-blur-sm animate-in fade-in" />

      {/* Dialog panel */}
      <div
        className={cn(
          "relative z-10 w-full max-w-md rounded-[var(--bcone-radius-lg)] bg-white shadow-[var(--bcone-shadow-lg)] p-6",
          className
        )}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
      >
        {variant === "destructive" && (
          <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-full bg-[var(--bcone-red)]/10">
            <AlertTriangle className="h-5 w-5 text-[var(--bcone-red)]" />
          </div>
        )}

        <h2
          id="confirm-dialog-title"
          className="text-lg font-black text-[var(--bcone-charcoal)]"
        >
          {title}
        </h2>
        <p className="mt-2 text-sm text-[var(--bcone-gray)] leading-relaxed">
          {message}
        </p>

        <div className="mt-6 flex justify-end gap-3">
          <Button variant="outline" onClick={onCancel}>
            {cancelText}
          </Button>
          <Button
            variant={variant === "destructive" ? "destructive" : "primary"}
            onClick={onConfirm}
          >
            {confirmText}
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
};
ConfirmDialog.displayName = "ConfirmDialog";
