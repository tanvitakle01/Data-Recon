import { useCallback, useState } from "react";
import api from "../../services/api";
import { BreakRateDonut, DateWindowTimeline, HotspotBarChart, UnmappedStackedBar, VarianceDistributionChart } from "./charts";
import RecordsTable from "./RecordsTable";

const STATUS_TONE = { match: "match", quantity_mismatch: "qty", missing_in_target: "missing", missing_in_source: "extra" };

// recharts hands click handlers slightly different shapes depending on the
// element (Pie vs Bar) — this normalizes to "wherever the original data item
// ended up" so every chart can share one filter-spec extraction.
function filterFromChartEntry(entry) {
  return entry?.filter || entry?.payload?.filter || null;
}

function StatTile({ label, count, pct, tone, onClick, active }) {
  return (
    <div
      onClick={onClick}
      style={{
        border: active ? "1px solid var(--accent)" : "1px solid var(--border)",
        borderRadius: "var(--radius-md)",
        padding: "10px 14px",
        cursor: onClick ? "pointer" : "default",
        background: active ? "var(--accent-ring)" : "transparent",
      }}
    >
      <span className={`status-badge status-badge--${tone}`}>
        <span className="status-badge__dot" />
        {label}
      </span>
      <div style={{ marginTop: 6, fontSize: 22, fontWeight: 800, color: "var(--ink)" }}>
        {count} <span style={{ fontSize: 12, fontWeight: 600, color: "var(--muted)" }}>({pct}%)</span>
      </div>
    </div>
  );
}

function Card({ title, hint, children }) {
  return (
    <section className="ct-card">
      <div className="ct-card__head">
        <h3 className="ct-card__title">{title}</h3>
        {hint && (
          <>
            <span className="ct-card__spacer" />
            <span className="ct-card__hint">{hint}</span>
          </>
        )}
      </div>
      <div className="ct-card__body">{children}</div>
    </section>
  );
}

export default function InsightsView({ payload, runId, uploadId }) {
  const { breakRate, hotspots = [], varianceDistribution = [], unmappedByField = [], dateCoverage } = payload || {};

  const [activeFilter, setActiveFilter] = useState(null);
  const [activeTitle, setActiveTitle] = useState("");
  const [records, setRecords] = useState(null);
  const [busy, setBusy] = useState(false);

  const idParams = runId ? { run_id: runId } : uploadId ? { upload_id: uploadId } : {};

  const runQuery = useCallback(
    async (filterSpec, title) => {
      if (!filterSpec) return;
      setActiveFilter(filterSpec);
      setActiveTitle(title);
      setBusy(true);
      try {
        const res = await api.post("/insights/records", { ...idParams, filter: filterSpec, pageSize: 200 });
        setRecords(res.data);
      } catch {
        setRecords({ columns: [], rows: [], totalMatched: 0 });
      } finally {
        setBusy(false);
      }
    },
    [runId, uploadId]
  );

  const onChartClick = (entry, title) => runQuery(filterFromChartEntry(entry), title);

  const clear = () => {
    setActiveFilter(null);
    setRecords(null);
  };

  const exportCsv = async () => {
    try {
      const res = await api.post(
        "/insights/records",
        { ...idParams, filter: activeFilter, format: "csv" },
        { responseType: "blob" }
      );
      const blobUrl = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = "insights_records.csv";
      a.click();
      URL.revokeObjectURL(blobUrl);
    } catch {
      // no-op — export failure isn't fatal to viewing insights
    }
  };

  if (!breakRate) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <Card title="Break-Rate Summary" hint="Click to drill in">
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap", alignItems: "center" }}>
          <BreakRateDonut results={breakRate.results} onSliceClick={(entry) => onChartClick(entry, entry?.payload?.label)} />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10, flex: 1, minWidth: 260 }}>
            {breakRate.results.map((r) => (
              <StatTile
                key={r.key}
                label={r.label}
                count={r.count}
                pct={r.pct}
                tone={STATUS_TONE[r.key]}
                active={activeFilter?.kind === "status" && activeFilter.value === r.key}
                onClick={() => runQuery(r.filter, r.label)}
              />
            ))}
          </div>
          <div style={{ display: "flex", gap: 20 }}>
            <div>
              <div style={{ fontSize: 10.5, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase" }}>Net Delta</div>
              <div style={{ marginTop: 4, fontSize: 17, fontWeight: 800, color: "var(--ink)" }}>{breakRate.netDelta}</div>
            </div>
            <div>
              <div style={{ fontSize: 10.5, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase" }}>Abs. Variance</div>
              <div style={{ marginTop: 4, fontSize: 17, fontWeight: 800, color: "var(--ink)" }}>{breakRate.totalAbsoluteVariance}</div>
            </div>
          </div>
        </div>
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 14 }}>
        {hotspots.map((section) => (
          <Card key={section.field} title={`Top ${section.rows.length} ${section.label}`} hint="by break count">
            {section.rows.length > 0 ? (
              <HotspotBarChart rows={section.rows} onBarClick={(entry) => onChartClick(entry, `${section.label}: ${entry?.value}`)} />
            ) : (
              <p className="wizard-field__help" style={{ margin: 0 }}>No breaking values.</p>
            )}
          </Card>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: unmappedByField.length ? "1fr 1fr" : "1fr", gap: 14 }}>
        {varianceDistribution.length > 0 && (
          <Card title="Variance Distribution" hint="Quartile bins, |delta|">
            <VarianceDistributionChart
              bins={varianceDistribution}
              onBarClick={(entry) => onChartClick(entry, `Variance ${entry?.min}–${entry?.max}`)}
            />
          </Card>
        )}

        {unmappedByField.length > 0 && (
          <Card title="Unmapped Values by Field">
            <UnmappedStackedBar
              rows={unmappedByField}
              onSegmentClick={(entry) => onChartClick(entry, `Unpaired values: ${entry?.label}`)}
            />
          </Card>
        )}
      </div>

      {dateCoverage && (
        <Card title="Date-Window Coverage">
          <DateWindowTimeline
            sourceMin={dateCoverage.sourceMin}
            sourceMax={dateCoverage.sourceMax}
            targetMin={dateCoverage.targetMin}
            targetMax={dateCoverage.targetMax}
          />
          <div style={{ marginTop: 14, display: "flex", gap: 24, flexWrap: "wrap" }}>
            <div style={{ cursor: "pointer" }} onClick={() => runQuery(dateCoverage.sourceOutsideWindowFilter, "Source dates outside target window")}>
              <div style={{ fontSize: 10.5, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase" }}>
                Source dates outside target window
              </div>
              <div style={{ marginTop: 4, fontSize: 17, fontWeight: 800, color: "var(--ink)" }}>
                {dateCoverage.sourceDatesOutsideTargetWindow}
              </div>
            </div>
            <div style={{ cursor: "pointer" }} onClick={() => runQuery(dateCoverage.targetOutsideWindowFilter, "Target dates outside source window")}>
              <div style={{ fontSize: 10.5, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase" }}>
                Target dates outside source window
              </div>
              <div style={{ marginTop: 4, fontSize: 17, fontWeight: 800, color: "var(--ink)" }}>
                {dateCoverage.targetDatesOutsideSourceWindow}
              </div>
            </div>
          </div>
        </Card>
      )}

      {activeFilter && records && (
        <RecordsTable
          title={activeTitle}
          columns={records.columns}
          rows={records.rows}
          totalMatched={records.totalMatched}
          onClear={clear}
          onExport={exportCsv}
          busy={busy}
        />
      )}
    </div>
  );
}
