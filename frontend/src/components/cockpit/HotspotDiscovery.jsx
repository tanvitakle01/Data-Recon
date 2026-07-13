import { useState } from "react";
import { FiInfo } from "react-icons/fi";
import { SectionShell, StatusPill } from "./CockpitPrimitives";
import { toneForLevel } from "./cockpitUtils";
import { useCockpitFilter } from "./useCockpitFilter";
import HotspotHeatmap from "./HotspotHeatmap";

const TILE_PALETTE = ["#1e3a8a", "#2563eb", "#3b82f6", "#60a5fa", "#93c5fd", "#bfdbfe"];

export function IssueBreakdownRow({ item }) {
  const breakdown = item.issueBreakdown || {};
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-100 bg-slate-50 px-3 py-2.5">
      <span className="text-slate-700 font-black text-xs">{item.entity ?? item.date}</span>
      {item.riskTier ? <StatusPill tone={toneForLevel(item.riskTier)}>{item.riskTier} risk</StatusPill> : null}
      <span className="text-slate-400 font-bold text-[10px]">
        Risk contribution: <span className="text-slate-700">{item.riskContribution}</span>
      </span>
      <span className="text-slate-400 font-bold text-[10px]">
        Missing: <span className="text-slate-700">{breakdown.missing ?? 0}</span>
      </span>
      <span className="text-slate-400 font-bold text-[10px]">
        Extra: <span className="text-slate-700">{breakdown.extra ?? 0}</span>
      </span>
      <span className="text-slate-400 font-bold text-[10px]">
        Qty Mismatch: <span className="text-slate-700">{breakdown.qtyMismatch ?? 0}</span>
      </span>
      <span className="text-slate-400 font-bold text-[10px]">
        Total: <span className="text-slate-700">{item.mismatchCount}</span> records
      </span>
    </div>
  );
}

/**
 * Proportional tile strip — a lightweight, real-data treemap: each tile's
 * width is driven by its actual share, not an equal grid column. No ECharts
 * treemap dependency needed for three-to-six items; plain flex-grow gets
 * the same "big problem = big tile" read. Each tile's info button reveals
 * the issue-type breakdown and risk contribution behind the bare percentage.
 */
function TileStrip({ title, dimension, items }) {
  const { drillTo } = useCockpitFilter();
  const [expanded, setExpanded] = useState(null);
  if (!items?.length) return null;

  const top = items.slice(0, 6);
  const expandedItem = top.find((item) => item.entity === expanded);
  const drill = (item) => drillTo({ dimension, value: item.entity, label: item.entity, source: "hotspotTile" });

  return (
    <div>
      <div className="text-slate-400 font-black text-[11px] uppercase tracking-wide mb-2">{title}</div>
      <div className="flex h-24 w-full gap-1 overflow-hidden rounded-xl">
        {top.map((item, idx) => (
          <div
            key={item.entity}
            role="button"
            tabIndex={0}
            onClick={() => drill(item)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") drill(item);
            }}
            style={{ flexGrow: Math.max(item.share, 4), background: TILE_PALETTE[idx] || "#1e293b" }}
            className="relative flex flex-col items-start justify-end p-2.5 text-left transition-opacity hover:opacity-90 min-w-[64px] cursor-pointer"
          >
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setExpanded((v) => (v === item.entity ? null : item.entity));
              }}
              className="absolute top-1.5 right-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-black/20 text-white/80 hover:bg-black/35"
              aria-label={`Show diagnostics for ${item.entity}`}
            >
              <FiInfo size={11} />
            </button>
            <span className="text-white font-black text-lg leading-none">{item.share}%</span>
            <span className="text-white/80 font-bold text-[10px] uppercase tracking-wide truncate max-w-full">{item.entity}</span>
          </div>
        ))}
      </div>

      {expandedItem ? <div className="mt-2"><IssueBreakdownRow item={expandedItem} /></div> : null}
    </div>
  );
}

function DateRankList({ dates }) {
  const { drillTo } = useCockpitFilter();
  const [expanded, setExpanded] = useState(null);
  if (!dates?.length) return null;

  return (
    <div>
      <div className="text-slate-400 font-black text-[11px] uppercase tracking-wide mb-2">Top Dates</div>
      <div className="space-y-1.5">
        {dates.slice(0, 5).map((d) => {
          const isExpanded = expanded === d.date;
          return (
            <div key={d.date} className="rounded-lg hover:bg-slate-50">
              <div className="flex w-full items-center gap-1 px-2 py-1.5">
                <button
                  type="button"
                  onClick={() => drillTo({ dimension: "date", value: d.date, label: d.date, source: "hotspotTile" })}
                  className="flex flex-1 items-center justify-between text-left"
                >
                  <span className="text-slate-600 font-bold text-xs">{d.date}</span>
                  <span className="text-slate-400 font-bold text-xs">{d.mismatchCount}</span>
                </button>
                <button
                  type="button"
                  onClick={() => setExpanded(isExpanded ? null : d.date)}
                  className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full text-slate-300 hover:text-blue-500"
                  aria-label={`Show diagnostics for ${d.date}`}
                >
                  <FiInfo size={12} />
                </button>
              </div>
              {isExpanded ? <div className="mx-2 mb-2"><IssueBreakdownRow item={d} /></div> : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Section 5 — where failures concentrate, using only what the payload
 * actually computes: Plants/Materials as proportional tiles, a Plant x Week
 * heatmap, and a compact date ranking. No fabricated Plant x Material or
 * Material x ExceptionType matrices — the backend doesn't aggregate those.
 */
export default function HotspotDiscovery({ hotspots }) {
  const { drillTo } = useCockpitFilter();
  if (!hotspots) return null;

  const { plants, materials, dates, matrix } = hotspots;
  const hasTiles = (plants?.length ?? 0) + (materials?.length ?? 0) > 0;
  const hasMatrix = (matrix?.cells?.length ?? 0) > 0;
  const hasDates = (dates?.length ?? 0) > 0;

  if (!hasTiles && !hasMatrix && !hasDates) return null;

  return (
    <SectionShell step="05" eyebrow="Where It Happened · Concentration" title="Hotspot Discovery">
      <div className="space-y-6">
        {hasTiles ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <TileStrip title="Plant Concentration" dimension="plant" items={plants} />
            <TileStrip title="Material Concentration" dimension="material" items={materials} />
          </div>
        ) : null}

        {hasMatrix ? (
          <div>
            <div className="text-slate-400 font-black text-[11px] uppercase tracking-wide mb-2">Plant × Week Heatmap</div>
            <HotspotHeatmap
              matrix={matrix}
              onCellClick={({ row }) => drillTo({ dimension: "plant", value: row, label: row, source: "hotspotMatrix" })}
            />
          </div>
        ) : null}

        {hasDates ? <DateRankList dates={dates} /> : null}
      </div>
    </SectionShell>
  );
}
