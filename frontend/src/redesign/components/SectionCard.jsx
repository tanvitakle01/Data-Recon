import { cn } from "../lib/cn";
import { Card } from "./Card";

/**
 * A labeled section container used to compose long wizard steps.
 * `index` shows a small chip (e.g. "A", "1"); `status` renders on the right.
 */
export function SectionCard({ index, title, description, status, actions, icon, children, className, bodyClassName }) {
  return (
    <Card className={cn("overflow-hidden", className)}>
      <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
        <div className="flex items-start gap-3 min-w-0">
          {index != null && (
            <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-accent-tint text-[12px] font-semibold text-accent-text">
              {index}
            </span>
          )}
          {icon && !index && (
            <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent-tint text-accent-text">
              {icon}
            </span>
          )}
          <div className="min-w-0">
            <h3 className="text-[15px] font-semibold tracking-[-0.01em] text-text">{title}</h3>
            {description && <p className="mt-0.5 text-[13px] text-muted">{description}</p>}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {status}
          {actions}
        </div>
      </div>
      <div className={cn("p-5", bodyClassName)}>{children}</div>
    </Card>
  );
}

export default SectionCard;
