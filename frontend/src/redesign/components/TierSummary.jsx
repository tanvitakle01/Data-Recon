import { cn } from "../lib/cn";
import { STATUS_CLASSES, TIER } from "../lib/status";

const TIER_ORDER = ["very_high", "high", "medium", "none", "out_of_scope"];

/** Compact strip of tier counts. `counts` keyed by tier code. */
export function TierSummary({ counts = {}, className }) {
  return (
    <div className={cn("flex flex-wrap gap-2", className)}>
      {TIER_ORDER.map((tier) => {
        const meta = TIER[tier];
        const c = STATUS_CLASSES[meta.status];
        const n = counts[tier] ?? 0;
        return (
          <div
            key={tier}
            className={cn("flex items-center gap-2 rounded-lg border bg-surface px-3 py-2", c.bd)}
          >
            <span className={cn("h-2 w-2 rounded-full", c.dot)} />
            <span className="text-[15px] font-semibold tabular-nums text-text">{n.toLocaleString()}</span>
            <span className={cn("text-[11px] font-medium uppercase tracking-[0.04em]", c.fg)}>{meta.label}</span>
          </div>
        );
      })}
    </div>
  );
}

/** Big classification stat tile (used on Results too). */
export function StatTile({ status = "neutral", value, label, className }) {
  const c = STATUS_CLASSES[status] || STATUS_CLASSES.neutral;
  return (
    <div className={cn("relative overflow-hidden rounded-xl border border-line bg-surface p-4 shadow-e1", className)}>
      <span className={cn("absolute left-0 top-0 h-full w-1", c.solid)} />
      <div className={cn("text-[26px] font-semibold tabular-nums tracking-[-0.02em]", c.fg)}>
        {typeof value === "number" ? value.toLocaleString() : value}
      </div>
      <div className="mt-0.5 text-[12px] font-medium text-muted">{label}</div>
    </div>
  );
}

export default TierSummary;
