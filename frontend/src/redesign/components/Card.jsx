import { cn } from "../lib/cn";

export function Card({ className, elevated = false, children, ...props }) {
  return (
    <div
      className={cn(
        "rounded-xl border border-line bg-surface",
        elevated ? "shadow-e2" : "shadow-e1",
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function CardHeader({ className, title, subtitle, actions, icon, children }) {
  if (children) return <div className={cn("px-5 py-4 border-b border-line", className)}>{children}</div>;
  return (
    <div className={cn("flex items-start justify-between gap-4 px-5 py-4 border-b border-line", className)}>
      <div className="flex items-start gap-3 min-w-0">
        {icon && (
          <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-tint text-accent-text">
            {icon}
          </div>
        )}
        <div className="min-w-0">
          {title && <h3 className="text-[15px] font-semibold tracking-[-0.01em] text-text truncate">{title}</h3>}
          {subtitle && <p className="mt-0.5 text-[13px] text-muted">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

export function CardBody({ className, children }) {
  return <div className={cn("p-5", className)}>{children}</div>;
}

export function CardFooter({ className, children }) {
  return <div className={cn("flex items-center gap-2 px-5 py-3.5 border-t border-line bg-surface-2/40 rounded-b-xl", className)}>{children}</div>;
}

export default Card;
