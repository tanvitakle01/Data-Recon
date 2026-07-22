import { cn } from "../lib/cn";
import { Check } from "lucide-react";

/** Large selectable card (Excel vs Live Fetch, comparison type, etc.). */
export function ChoiceCard({ icon, title, description, selected, onClick, recommended, badge, className }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "group relative flex w-full flex-col items-start gap-3 rounded-xl border p-5 text-left transition-all duration-150",
        selected
          ? "border-accent bg-accent-tint/50 ring-2 ring-accent-ring shadow-e1"
          : "border-line bg-surface hover:border-line-3 hover:shadow-e1",
        className
      )}
    >
      <div className="flex w-full items-start justify-between">
        <div className={cn(
          "flex h-10 w-10 items-center justify-center rounded-lg transition-colors",
          selected ? "bg-accent text-on-accent" : "bg-surface-2 text-muted group-hover:text-text"
        )}>
          {icon}
        </div>
        <div className="flex items-center gap-2">
          {recommended && <span className="rounded-full bg-accent-tint px-2 py-0.5 text-[11px] font-medium text-accent-text">Recommended</span>}
          {badge}
          <span className={cn(
            "flex h-5 w-5 items-center justify-center rounded-full border transition-colors",
            selected ? "border-accent bg-accent text-on-accent" : "border-line-3 bg-surface"
          )}>
            {selected && <Check className="h-3 w-3" strokeWidth={3} />}
          </span>
        </div>
      </div>
      <div>
        <h3 className="text-[15px] font-semibold tracking-[-0.01em] text-text">{title}</h3>
        {description && <p className="mt-1 text-[13px] leading-relaxed text-muted">{description}</p>}
      </div>
    </button>
  );
}

export default ChoiceCard;
