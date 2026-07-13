import { SectionShell } from "../cockpit/CockpitPrimitives";
import { IssueBreakdownRow } from "../cockpit/HotspotDiscovery";

/**
 * Executive Summary, section 5 — Hotspot Analysis, condensed to the top 3
 * plants and materials. Reuses `IssueBreakdownRow` from Detailed Insights'
 * Hotspot Discovery so issue-type counts and risk contribution read
 * identically in both tabs.
 */
export default function HotspotSummaryCard({ hotspots }) {
  const plants = hotspots?.plants?.slice(0, 3) || [];
  const materials = hotspots?.materials?.slice(0, 3) || [];
  if (!plants.length && !materials.length) return null;

  return (
    <SectionShell eyebrow="Where It Concentrates" title="Hotspot Analysis">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {plants.length ? (
          <div>
            <div className="mb-2 text-[11px] font-black uppercase tracking-wide text-slate-400">Top Plants / Locations</div>
            <div className="space-y-2">
              {plants.map((p) => (
                <IssueBreakdownRow key={p.entity} item={p} />
              ))}
            </div>
          </div>
        ) : null}
        {materials.length ? (
          <div>
            <div className="mb-2 text-[11px] font-black uppercase tracking-wide text-slate-400">Top Materials</div>
            <div className="space-y-2">
              {materials.map((m) => (
                <IssueBreakdownRow key={m.entity} item={m} />
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </SectionShell>
  );
}
