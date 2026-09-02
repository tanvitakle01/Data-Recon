import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

// Fixed, mode-invariant status scale (validated separately from the app's
// text-badge colors — see index.css's --chart-good/… comment for why the
// badge reds can't double as chart fill colors). Always rendered with an
// icon + label, never color alone.
const STATUS_CHART_COLOR = {
  match: "var(--chart-good)",
  quantity_mismatch: "var(--chart-warning)",
  missing_in_target: "var(--chart-critical)",
  missing_in_source: "var(--chart-serious)",
};

const TOOLTIP_STYLE = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-md)",
  boxShadow: "var(--shadow-2)",
  fontSize: 12.5,
  color: "var(--ink)",
};
const TOOLTIP_LABEL_STYLE = { color: "var(--ink)", fontWeight: 700, marginBottom: 4 };
const TOOLTIP_ITEM_STYLE = { color: "var(--ink-2)" };

// ── Break-rate donut — part-to-whole across the four record statuses.
// No built-in legend here by design: the stat-tile row immediately below it
// (in InsightsView) already pairs each status's color dot with its label and
// exact count/pct — that row *is* the legend, so the chart isn't duplicated.
export function BreakRateDonut({ results, onSliceClick }) {
  const data = results.map((r) => ({ ...r, color: STATUS_CHART_COLOR[r.key] || "var(--muted)" }));
  const total = data.reduce((sum, r) => sum + r.count, 0);

  return (
    <div style={{ position: "relative", width: 200, height: 200 }}>
      <ResponsiveContainer>
        <PieChart>
          <Pie
            data={data}
            dataKey="count"
            nameKey="label"
            innerRadius={56}
            outerRadius={92}
            paddingAngle={data.length > 1 ? 2 : 0}
            cornerRadius={3}
            stroke="var(--surface)"
            strokeWidth={2}
            onClick={(entry) => onSliceClick(entry)}
            style={{ cursor: "pointer" }}
            isAnimationActive={false}
          >
            {data.map((r) => (
              <Cell key={r.key} fill={r.color} />
            ))}
          </Pie>
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            labelStyle={TOOLTIP_LABEL_STYLE}
            itemStyle={TOOLTIP_ITEM_STYLE}
            formatter={(value, _name, entry) => [`${value} (${entry.payload.pct}%)`, entry.payload.label]}
          />
        </PieChart>
      </ResponsiveContainer>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexDirection: "column",
          pointerEvents: "none",
        }}
      >
        <div style={{ fontSize: 20, fontWeight: 800, color: "var(--ink)" }}>{total}</div>
        <div style={{ fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", color: "var(--muted)" }}>Total</div>
      </div>
    </div>
  );
}

// ── Hotspot ranking — single-hue magnitude bars, no legend needed (one series) ──
export function HotspotBarChart({ rows, onBarClick }) {
  const data = [...rows].reverse(); // recharts vertical layout renders top-to-bottom bottom-up
  const height = Math.max(120, data.length * 30);

  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 36, bottom: 4, left: 4 }}>
          <XAxis type="number" hide />
          <YAxis
            type="category"
            dataKey="value"
            width={110}
            tick={{ fill: "var(--muted)", fontSize: 11.5 }}
            axisLine={{ stroke: "var(--chart-grid)" }}
            tickLine={false}
          />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            labelStyle={TOOLTIP_LABEL_STYLE}
            itemStyle={TOOLTIP_ITEM_STYLE}
            formatter={(value, name) => [value, name === "breakCount" ? "Break count" : name]}
          />
          <Bar
            dataKey="breakCount"
            fill="var(--chart-blue)"
            barSize={16}
            radius={[0, 4, 4, 0]}
            onClick={(entry) => onBarClick(entry)}
            style={{ cursor: "pointer" }}
            isAnimationActive={false}
          >
            <LabelList dataKey="breakCount" position="right" style={{ fill: "var(--ink)", fontSize: 11, fontWeight: 700 }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Variance distribution — one hue, monotone-darker bins (validated ordinal ramp) ──
const SEQUENTIAL_STEPS = ["var(--chart-seq-1)", "var(--chart-seq-2)", "var(--chart-seq-3)", "var(--chart-seq-4)"];

export function VarianceDistributionChart({ bins, onBarClick }) {
  const data = bins.map((b, i) => ({ ...b, range: `${b.min}–${b.max}`, color: SEQUENTIAL_STEPS[i % SEQUENTIAL_STEPS.length] }));

  return (
    <div style={{ width: "100%", height: 180 }}>
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 16, right: 8, bottom: 4, left: 8 }}>
          <XAxis dataKey="range" tick={{ fill: "var(--muted)", fontSize: 11.5 }} axisLine={{ stroke: "var(--chart-grid)" }} tickLine={false} />
          <YAxis hide />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            labelStyle={TOOLTIP_LABEL_STYLE}
            itemStyle={TOOLTIP_ITEM_STYLE}
            formatter={(value, name) => [value, name === "count" ? "Records" : "Total abs. variance"]}
          />
          <Bar dataKey="count" barSize={40} radius={[4, 4, 0, 0]} onClick={(entry) => onBarClick(entry)} style={{ cursor: "pointer" }} isAnimationActive={false}>
            {data.map((d, i) => (
              <Cell key={i} fill={d.color} />
            ))}
            <LabelList dataKey="count" position="top" style={{ fill: "var(--ink)", fontSize: 11, fontWeight: 700 }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Unmapped-by-field — part-to-whole per field, status colors (paired = good) ──
export function UnmappedStackedBar({ rows, onSegmentClick }) {
  const height = Math.max(80, rows.length * 34);

  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer>
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 4 }}>
          <XAxis type="number" hide />
          <YAxis
            type="category"
            dataKey="label"
            width={130}
            tick={{ fill: "var(--muted)", fontSize: 11.5 }}
            axisLine={{ stroke: "var(--chart-grid)" }}
            tickLine={false}
          />
          <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={TOOLTIP_LABEL_STYLE} itemStyle={TOOLTIP_ITEM_STYLE} />
          <Legend
            verticalAlign="top"
            height={28}
            formatter={(value) => <span style={{ color: "var(--ink)", fontSize: 12 }}>{value}</span>}
          />
          <Bar
            dataKey="paired"
            name="Paired"
            stackId="a"
            fill="var(--chart-good)"
            barSize={16}
            onClick={(entry) => onSegmentClick(entry, "paired")}
            style={{ cursor: "pointer" }}
            isAnimationActive={false}
          />
          <Bar
            dataKey="unpaired"
            name="Unpaired"
            stackId="a"
            fill="var(--chart-critical)"
            barSize={16}
            radius={[0, 4, 4, 0]}
            onClick={(entry) => onSegmentClick(entry, "unpaired")}
            style={{ cursor: "pointer" }}
            isAnimationActive={false}
          >
            <LabelList dataKey="unpaired" position="right" style={{ fill: "var(--ink)", fontSize: 11, fontWeight: 700 }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Date-window coverage — a plain two-row range timeline, not recharts ─────
// Two series (source/target) on a shared axis: a form recharts' bar/line
// primitives don't fit cleanly, so this is hand-built — categorical color
// (blue/aqua, slots 1 & 3 of the validated categorical order) with a legend.
export function DateWindowTimeline({ sourceMin, sourceMax, targetMin, targetMax }) {
  const dates = [sourceMin, sourceMax, targetMin, targetMax].filter(Boolean).map((d) => new Date(d).getTime());
  if (!dates.length) return null;
  const lo = Math.min(...dates);
  const hi = Math.max(...dates);
  const span = Math.max(1, hi - lo);

  const pct = (d) => ((new Date(d).getTime() - lo) / span) * 100;

  const rows = [
    { label: "Source", min: sourceMin, max: sourceMax, color: "var(--chart-blue)" },
    { label: "Target", min: targetMin, max: targetMax, color: "var(--chart-aqua)" },
  ].filter((r) => r.min && r.max);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {rows.map((r) => {
        const left = pct(r.min);
        const width = Math.max(1, pct(r.max) - left);
        return (
          <div key={r.label} style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ width: 56, fontSize: 12, fontWeight: 700, color: "var(--muted)" }}>{r.label}</div>
            <div style={{ position: "relative", flex: 1, height: 14, background: "var(--surface-2)", borderRadius: 7 }}>
              <div
                title={`${r.min} – ${r.max}`}
                style={{
                  position: "absolute",
                  left: `${left}%`,
                  width: `${width}%`,
                  height: "100%",
                  background: r.color,
                  borderRadius: 7,
                }}
              />
            </div>
            <div style={{ width: 190, fontSize: 11.5, color: "var(--muted)", textAlign: "right" }}>
              {r.min} – {r.max}
            </div>
          </div>
        );
      })}
    </div>
  );
}
