import * as React from "react";
import { cn } from "../../lib/utils";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, label, error, hint, id, ...props }, ref) => {
    const inputId = id ?? label?.toLowerCase().replace(/\s+/g, "-");
    return (
      <div className="flex flex-col gap-1">
        {label && (
          <label
            htmlFor={inputId}
            className="text-sm font-bold text-[var(--bcone-charcoal)]"
          >
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={cn(
            "h-10 w-full rounded-[var(--bcone-radius-sm)] border px-3 text-sm text-[var(--bcone-charcoal)] placeholder:text-[var(--bcone-gray)] transition-colors",
            "focus:outline-none focus:ring-2 focus:ring-[var(--bcone-teal)] focus:border-transparent",
            "disabled:cursor-not-allowed disabled:opacity-50",
            error
              ? "border-[var(--bcone-red)] focus:ring-[var(--bcone-red)]"
              : "border-[var(--bcone-gray)]",
            className
          )}
          aria-describedby={error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined}
          {...props}
        />
        {error && (
          <p id={`${inputId}-error`} className="text-xs text-[var(--bcone-red)]" role="alert">
            {error}
          </p>
        )}
        {hint && !error && (
          <p id={`${inputId}-hint`} className="text-xs text-[var(--bcone-gray)]">
            {hint}
          </p>
        )}
      </div>
    );
  }
);

Input.displayName = "Input";

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, label, error, hint, id, rows = 4, ...props }, ref) => {
    const inputId = id ?? label?.toLowerCase().replace(/\s+/g, "-");
    return (
      <div className="flex flex-col gap-1">
        {label && (
          <label htmlFor={inputId} className="text-sm font-bold text-[var(--bcone-charcoal)]">
            {label}
          </label>
        )}
        <textarea
          ref={ref}
          id={inputId}
          rows={rows}
          className={cn(
            "w-full rounded-[var(--bcone-radius-sm)] border px-3 py-2 text-sm text-[var(--bcone-charcoal)] placeholder:text-[var(--bcone-gray)] transition-colors resize-y",
            "focus:outline-none focus:ring-2 focus:ring-[var(--bcone-teal)] focus:border-transparent",
            "disabled:cursor-not-allowed disabled:opacity-50",
            error ? "border-[var(--bcone-red)]" : "border-[var(--bcone-gray)]",
            className
          )}
          {...props}
        />
        {error && <p className="text-xs text-[var(--bcone-red)]" role="alert">{error}</p>}
        {hint && !error && <p className="text-xs text-[var(--bcone-gray)]">{hint}</p>}
      </div>
    );
  }
);

Textarea.displayName = "Textarea";
