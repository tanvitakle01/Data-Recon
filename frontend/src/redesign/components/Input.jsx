import { cn } from "../lib/cn";

export function Field({ label, hint, error, required, htmlFor, className, children }) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      {label && (
        <label htmlFor={htmlFor} className="text-[13px] font-medium text-text-secondary">
          {label} {required && <span className="text-missing-fg">*</span>}
        </label>
      )}
      {children}
      {error ? (
        <p className="text-xs text-missing-fg">{error}</p>
      ) : hint ? (
        <p className="text-xs text-muted">{hint}</p>
      ) : null}
    </div>
  );
}

const base =
  "w-full rounded-lg border bg-surface px-3 text-sm text-text placeholder:text-faint " +
  "transition-[border-color,box-shadow] duration-150 outline-none " +
  "focus:border-accent focus:ring-2 focus:ring-accent-ring disabled:opacity-50 disabled:bg-surface-2";

export function Input({ className, mono = false, invalid = false, ...props }) {
  return (
    <input
      className={cn(
        base,
        "h-[34px]",
        mono && "font-mono text-[13px]",
        invalid ? "border-missing-bd focus:border-missing-fg focus:ring-missing-bd" : "border-line-2",
        className
      )}
      {...props}
    />
  );
}

export function Textarea({ className, invalid = false, rows = 3, ...props }) {
  return (
    <textarea
      rows={rows}
      className={cn(base, "py-2 resize-y", invalid ? "border-missing-bd" : "border-line-2", className)}
      {...props}
    />
  );
}

export default Input;
