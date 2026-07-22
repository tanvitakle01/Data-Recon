import { cn } from "../lib/cn";

export function EmptyState({ icon, title, description, action, className }) {
  return (
    <div className={cn("flex flex-col items-center justify-center rounded-xl border border-dashed border-line-2 bg-surface-2/40 px-6 py-12 text-center", className)}>
      {icon && (
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-surface text-muted shadow-e1 ring-1 ring-line">
          {icon}
        </div>
      )}
      {title && <h4 className="text-sm font-semibold text-text">{title}</h4>}
      {description && <p className="mt-1 max-w-sm text-[13px] text-muted">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export default EmptyState;
