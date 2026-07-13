import { useEffect, useState } from "react";
import { FiChevronDown, FiX, FiTerminal } from "react-icons/fi";
import api from "../../services/api";
import { SectionShell } from "./CockpitPrimitives";
import { useCockpitFilter } from "./useCockpitFilter";

const MAX_COLUMNS = 8;

/**
 * Section 8 — deliberately separated from the executive read above by a
 * plain-language divider, and collapsed by default: executives never see
 * raw records unless they choose to. Every clickable insight in the cockpit
 * (hotspot, root cause, business impact, exception category) drives this
 * panel via CockpitFilterContext — it auto-opens and scrolls into view, so
 * nothing above is a dead-end visualization.
 */
export default function AnalystWorkspace({ fileId, runId }) {
  const drilldownId = runId || fileId;
  const { filter, clearFilter, workspaceRef, open, setOpen } = useCockpitFilter();
  const [rows, setRows] = useState([]);
  const [columns, setColumns] = useState([]);
  const [totalMatched, setTotalMatched] = useState(0);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState(null);

  useEffect(() => {
    if (!open || !drilldownId) return;

    const run = async () => {
      setLoading(true);
      setFetchError(null);
      try {
        const filters = {};
        if (filter?.dimension === "exceptionType") {
          filters.exceptionType = filter.value;
        } else if (filter?.dimension) {
          filters.dimension = filter.dimension;
          filters.value = filter.value;
        }

        const body = runId ? { run_id: runId, filters, limit: 100 } : { file_id: fileId, filters, limit: 100 };
        const res = await api.post("/insights/drilldown", body);
        setRows(res.data?.rows ?? []);
        setColumns((res.data?.columns ?? []).slice(0, MAX_COLUMNS));
        setTotalMatched(res.data?.totalMatched ?? 0);
      } catch (e) {
        setFetchError(e?.response?.data?.detail || "Failed to load transactions");
      } finally {
        setLoading(false);
      }
    };

    run();
  }, [open, drilldownId, runId, fileId, filter?.dimension, filter?.value, filter?.ts]);

  if (!drilldownId) return null;

  return (
    <div>
      <div className="flex items-center gap-3 mb-4 px-1">
        <div className="h-px flex-1 bg-slate-200" />
        <span className="inline-flex items-center gap-1.5 text-slate-400 font-bold text-xs uppercase tracking-widest">
          <FiTerminal size={12} /> For Analysts
        </span>
        <div className="h-px flex-1 bg-slate-200" />
      </div>

      <SectionShell
        step="08"
        eyebrow="Record-Level Detail · Optional"
        title="Analyst Workspace"
        className="scroll-mt-6"
        actions={
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-extrabold text-slate-600 hover:bg-slate-50"
          >
            {open ? "Collapse" : "Expand"}
            <FiChevronDown className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
          </button>
        }
      >
        <div ref={workspaceRef} />

        {filter?.label ? (
          <div className="mb-4 flex items-center gap-2 flex-wrap font-mono">
            <span className="text-slate-400 font-bold text-xs">investigating ›</span>
            <span className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-bold text-blue-800">
              {filter.label}
              <button type="button" onClick={clearFilter} aria-label="Clear filter">
                <FiX className="text-blue-500 hover:text-blue-700" />
              </button>
            </span>
            {filter.evidence ? <span className="text-slate-400 font-medium text-xs">{filter.evidence}</span> : null}
          </div>
        ) : (
          <div className="mb-4 text-slate-400 font-semibold text-sm">
            Click any hotspot, root cause, or exception category above to inspect the underlying transactions here.
          </div>
        )}

        {!open ? null : loading ? (
          <div className="text-slate-400 font-bold text-sm py-6 text-center">Loading transactions…</div>
        ) : fetchError ? (
          <div className="text-red-600 font-semibold text-sm">{fetchError}</div>
        ) : rows.length === 0 ? (
          <div className="text-slate-400 font-semibold text-sm py-6 text-center">No matching transactions.</div>
        ) : (
          <div>
            <div className="text-slate-400 font-mono font-semibold text-xs mb-2">
              {rows.length} / {totalMatched} record{totalMatched === 1 ? "" : "s"}
            </div>
            <div className="max-h-[420px] overflow-auto rounded-xl border border-mint-200">
              <table className="w-full text-xs border-collapse font-mono">
                <thead>
                  <tr>
                    {columns.map((col) => (
                      <th key={col} className="sticky top-0 z-10 bg-mint-50 text-left px-3 py-2.5 font-bold text-slate-600 uppercase tracking-wide border-b border-mint-200 whitespace-nowrap">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="bg-white">
                  {rows.map((row, idx) => (
                    <tr key={idx} className="hover:bg-mint-50">
                      {columns.map((col) => (
                        <td key={col} className="px-3 py-2 border-b border-mint-100 text-slate-700 whitespace-nowrap">
                          {row[col] === null || row[col] === undefined ? "—" : String(row[col])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </SectionShell>
    </div>
  );
}
