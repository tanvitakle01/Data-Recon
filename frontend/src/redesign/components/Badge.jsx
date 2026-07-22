import { cn } from "../lib/cn";
import { STATUS_CLASSES, TIER, OUTCOME, CHANGE } from "../lib/status";

/**
 * Semantic badge. `status` is one of the 8 status keys (+ neutral).
 * emphasis: "soft" (tinted chip, default) | "solid" (filled).
 * Set `dot` for a leading status dot.
 */
export function Badge({ status = "neutral", emphasis = "soft", dot = false, className, children }) {
  const c = STATUS_CLASSES[status] || STATUS_CLASSES.neutral;
  const solid = emphasis === "solid";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium leading-none",
        solid ? cn(c.solid, "text-white") : cn(c.bg, c.fg, "border", c.bd),
        className
      )}
    >
      {dot && (
        <span className={cn("h-1.5 w-1.5 rounded-full", solid ? "bg-white/80" : c.dot)} />
      )}
      {children}
    </span>
  );
}

/** Convenience wrappers that resolve domain enums -> status + label. */
export function TierBadge({ tier, dot = true, ...rest }) {
  const t = TIER[tier] || { status: "neutral", label: String(tier ?? "—") };
  return <Badge status={t.status} dot={dot} {...rest}>{t.label}</Badge>;
}

export function OutcomeBadge({ outcome, dot = true, ...rest }) {
  const o = OUTCOME[outcome] || { status: "neutral", label: String(outcome ?? "—") };
  return <Badge status={o.status} dot={dot} {...rest}>{o.label}</Badge>;
}

export function ChangeBadge({ change, ...rest }) {
  const c = CHANGE[change] || { status: "neutral", label: String(change ?? "—") };
  return <Badge status={c.status} {...rest}>{c.label}</Badge>;
}

export default Badge;
