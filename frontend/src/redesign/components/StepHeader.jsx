import { cn } from "../lib/cn";

export function StepHeader({ step, total, eyebrow, title, description, actions, className }) {
  return (
    <header className={cn("sticky top-0 z-20 border-b border-line bg-bg/80 px-8 py-5 backdrop-blur-md", className)}>
      <div className="flex items-start justify-between gap-6">
        <div className="min-w-0">
          <div className="mb-1.5 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
            {step && total && <span>Step {step} of {total}</span>}
            {eyebrow && (
              <>
                <span className="text-line-3">·</span>
                <span className="text-accent-text">{eyebrow}</span>
              </>
            )}
          </div>
          <h1 className="text-[22px] font-semibold tracking-[-0.015em] text-text">{title}</h1>
          {description && <p className="mt-1 max-w-2xl text-[13px] leading-relaxed text-muted">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}

export default StepHeader;
