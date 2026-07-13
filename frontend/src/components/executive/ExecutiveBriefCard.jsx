import { SectionShell, CopyButton } from "../cockpit/CockpitPrimitives";

/**
 * Executive Summary, section 2 — the deterministic Python-generated brief
 * (`cockpit.executiveBriefBullets`), rendered as a scannable bullet list
 * rather than a paragraph. Every line is produced by
 * `generate_executive_brief_bullets` in insight_adapter.py from numbers
 * already shown elsewhere in this payload — no invented text.
 */
export default function ExecutiveBriefCard({ bullets }) {
  const items = Array.isArray(bullets) ? bullets.filter(Boolean) : [];
  if (!items.length) return null;

  return (
    <SectionShell
      eyebrow="Executive Narrative"
      title="Executive Brief"
      actions={<CopyButton text={items.join("\n")} label="Copy Brief" />}
    >
      <ul className="m-0 list-none space-y-2.5 p-0">
        {items.map((line, idx) => (
          <li key={idx} className="flex items-start gap-2.5 text-sm font-semibold leading-relaxed text-slate-800">
            <span className="mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-blue-500" />
            {line}
          </li>
        ))}
      </ul>
    </SectionShell>
  );
}
