import { useId, useState } from "react";
import { FiInfo, FiChevronDown } from "react-icons/fi";
import { toneToHex, toneForLevel } from "./cockpitUtils";

const TONE_CLASSES = {
  success: "bg-emerald-50 text-emerald-800 border-emerald-200",
  warning: "bg-amber-50 text-amber-800 border-amber-200",
  danger: "bg-red-50 text-red-800 border-red-200",
  neutral: "bg-slate-100 text-slate-700 border-slate-200",
  info: "bg-blue-50 text-blue-800 border-blue-200",
};

/** Same pill shape as RiskBadge, generalized to any tone/label so callers
 * don't have to route every status label through an accuracy/score number. */
export function StatusPill({ tone = "neutral", children }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-extrabold ${TONE_CLASSES[tone] || TONE_CLASSES.neutral}`}>
      {children}
    </span>
  );
}

/** Standard cockpit card shell — rounded-3xl border-slate-200 bg-white/70,
 * the same wrapper convention already used by ExecutiveSummaryCard and every
 * insights/*.jsx card, so new sections look like a natural extension. The
 * optional `step` badge and larger title scale exist so the eight sections
 * read as a numbered investigation story instead of equal-weight widgets. */
export function SectionShell({ step, eyebrow, title, actions, children, className = "" }) {
  return (
    <section className={`rounded-3xl border border-slate-200 bg-white/70 backdrop-blur-sm p-6 md:p-8 shadow-[0_10px_30px_rgba(2,6,23,0.04)] transition-shadow duration-300 hover:shadow-[0_16px_40px_rgba(2,6,23,0.07)] ${className}`}>
      {(title || actions) && (
        <div className="flex items-start justify-between gap-4 mb-6">
          <div className="flex items-start gap-3.5">
            {step ? (
              <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-mint-700 to-mint-900 text-white text-xs font-black tabular-nums shadow-[0_4px_12px_rgba(95,196,182,0.3)]">
                {step}
              </div>
            ) : null}
            <div>
              {eyebrow ? (
                <div className="text-slate-400 font-bold text-[11px] uppercase tracking-widest mb-1.5">{eyebrow}</div>
              ) : null}
              {title ? <h2 className="text-slate-900 font-black text-2xl md:text-[26px] tracking-tight leading-none m-0">{title}</h2> : null}
            </div>
          </div>
          {actions ? <div className="flex items-center gap-2 flex-shrink-0">{actions}</div> : null}
        </div>
      )}
      {children}
    </section>
  );
}

/** "Copy to clipboard" affordance with a brief inline confirmation instead
 * of a toast library — small, deliberate, no new dependency. */
export function CopyButton({ text, label = "Copy" }) {
  const [copied, setCopied] = useState(false);

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard API unavailable (e.g. insecure context) — fail silently, no crash.
    }
  };

  return (
    <button
      type="button"
      onClick={onCopy}
      className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-extrabold text-slate-600 hover:border-slate-300 hover:bg-slate-50 transition-colors"
    >
      {copied ? "Copied" : label}
    </button>
  );
}

/** Hover/focus-triggered explanation bubble — the "why does this label exist"
 * affordance for static classification thresholds (severity, health) that
 * don't have a full drill-down of their own. No new dependency: a positioned
 * absolute `<div>`, shown/hidden on hover and keyboard focus alike. */
export function InfoTooltip({ text, side = "top" }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  if (!text) return null;

  return (
    <span className="relative inline-flex">
      <button
        type="button"
        aria-describedby={id}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className="inline-flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full text-slate-300 hover:text-blue-500 focus:text-blue-500 focus:outline-none"
        aria-label="More information"
      >
        <FiInfo size={13} />
      </button>
      {open ? (
        <span
          id={id}
          role="tooltip"
          className={`absolute z-30 w-56 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-[11px] font-semibold leading-snug text-white shadow-xl ${
            side === "top" ? "bottom-full left-1/2 -translate-x-1/2 mb-2" : "top-full left-1/2 -translate-x-1/2 mt-2"
          }`}
        >
          {text}
        </span>
      ) : null}
    </span>
  );
}

/** Generic "Why?" disclosure — the one expand/collapse pattern reused by
 * Recon Score, Readiness, Confidence, Hotspots, and Root Causes so every
 * "explain this number" interaction looks and behaves identically. */
export function WhyPanel({ label = "Why this number?", openLabel = "Hide breakdown", defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 text-blue-600 font-extrabold text-xs hover:text-blue-700"
        aria-expanded={open}
      >
        {open ? openLabel : label}
        <FiChevronDown className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`} size={12} />
      </button>
      {open ? <div className="mt-3 rounded-2xl border border-slate-100 bg-slate-50/80 p-4">{children}</div> : null}
    </div>
  );
}

/** One row of a weighted breakdown: bar length IS contributionPct, so the
 * visual proportion matches the arithmetic exactly (used for Recon Score
 * contributors and reusable for any other weight/count/impact triple). */
export function ContributorBar({ name, count, unit = "records", sharePct, contributionPct, penaltyPoints, impact }) {
  const tone = toneForLevel(impact);
  const color = toneToHex(tone);
  const barWidth = Math.max(2, Math.round(contributionPct || 0));

  return (
    <div className="py-2 first:pt-0 last:pb-0">
      <div className="flex items-center justify-between gap-3 mb-1.5">
        <span className="text-slate-700 font-bold text-xs truncate">{name}</span>
        <div className="flex flex-shrink-0 items-center gap-2">
          <span className="text-slate-400 font-semibold text-[11px] tabular-nums">
            {count} {unit} · {sharePct}%
          </span>
          <StatusPill tone={tone}>{impact}</StatusPill>
        </div>
      </div>
      <div className="h-1.5 w-full rounded-full bg-slate-200 overflow-hidden">
        <div
          className="h-full rounded-full transition-[width] duration-700 ease-out"
          style={{ width: `${barWidth}%`, background: color }}
        />
      </div>
      {penaltyPoints != null ? (
        <div className="mt-1 text-[10px] text-slate-400 font-bold tabular-nums">
          −{penaltyPoints} pts · {contributionPct}% of total deduction
        </div>
      ) : null}
    </div>
  );
}
