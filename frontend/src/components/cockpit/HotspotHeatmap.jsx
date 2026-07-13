import { useMemo } from "react";
import ReactECharts from "echarts-for-react";

const EMPTY_CELLS = [];

/**
 * The one deliberate ECharts usage in the cockpit: Recharts has no heatmap
 * primitive, and hand-rolling a colored-grid-of-divs would be more code than
 * this single component. Everything else in the cockpit stays on Recharts.
 */
export default function HotspotHeatmap({ matrix, onCellClick }) {
  const cells = matrix?.cells ?? EMPTY_CELLS;

  const { rows, cols, data, maxValue } = useMemo(() => {
    const rowSet = [];
    const colSet = [];
    cells.forEach((c) => {
      if (!rowSet.includes(c.row)) rowSet.push(c.row);
      if (!colSet.includes(c.col)) colSet.push(c.col);
    });
    colSet.sort();
    const points = cells.map((c) => [colSet.indexOf(c.col), rowSet.indexOf(c.row), c.value]);
    const max = cells.reduce((acc, c) => Math.max(acc, c.value), 0);
    return { rows: rowSet, cols: colSet, data: points, maxValue: max || 1 };
  }, [cells]);

  if (!cells.length) return null;

  const option = {
    tooltip: {
      position: "top",
      formatter: (params) => {
        const [colIdx, rowIdx, value] = params.value;
        return `<b>${rows[rowIdx]}</b> · ${cols[colIdx]}<br/>${value} exceptions`;
      },
    },
    grid: { left: 90, right: 20, top: 10, bottom: 60 },
    xAxis: {
      type: "category",
      data: cols,
      splitArea: { show: true },
      axisLabel: { rotate: 45, fontSize: 11, color: "#64748b" },
    },
    yAxis: {
      type: "category",
      data: rows,
      splitArea: { show: true },
      axisLabel: { fontSize: 12, color: "#334155", fontWeight: 700 },
    },
    visualMap: {
      min: 0,
      max: maxValue,
      calculable: false,
      show: false,
      inRange: { color: ["#eff6ff", "#93c5fd", "#2563eb", "#1e3a8a"] },
    },
    series: [
      {
        type: "heatmap",
        data,
        label: { show: true, fontSize: 11, fontWeight: 700 },
        emphasis: { itemStyle: { shadowBlur: 8, shadowColor: "rgba(37,99,235,0.35)" } },
        itemStyle: { borderRadius: 4, borderColor: "#fff", borderWidth: 2 },
      },
    ],
  };

  return (
    <ReactECharts
      option={option}
      style={{ height: Math.max(220, rows.length * 42) }}
      onEvents={{
        click: (params) => {
          if (!onCellClick) return;
          const [colIdx, rowIdx] = params.value;
          onCellClick({ row: rows[rowIdx], col: cols[colIdx] });
        },
      }}
    />
  );
}
