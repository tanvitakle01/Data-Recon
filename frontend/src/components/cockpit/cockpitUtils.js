export function toneForLevel(level) {
  const l = String(level || "").toLowerCase();
  if (l === "critical" || l === "high" || l === "fail") return "danger";
  if (l === "medium" || l === "partial") return "warning";
  if (l === "low" || l === "pass") return "success";
  return "neutral";
}

// System Health uses its own vocabulary (Degraded/Attention Needed/Healthy)
// rather than High/Medium/Low, so it gets its own mapping into the same tones.
export function toneForHealth(health) {
  const h = String(health || "").toLowerCase();
  if (h === "degraded") return "danger";
  if (h === "attention needed") return "warning";
  if (h === "healthy") return "success";
  return "neutral";
}

// Single source of truth for tone -> color across the cockpit (gauges,
// bars, pills, dots) so every "danger" reads as the same red everywhere.
export const TONE_HEX = {
  success: "#10b981",
  warning: "#f59e0b",
  danger: "#ef4444",
  info: "#2563eb",
  neutral: "#94a3b8",
};

export function toneToHex(tone) {
  return TONE_HEX[tone] || TONE_HEX.neutral;
}

// Same red/amber/emerald semantics as toneForLevel, as hex values for SVG
// stroke/fill where a Tailwind class can't reach (gauge rings, heatmap-adjacent visuals).
export function scoreToHex(score) {
  const n = Number(score) || 0;
  if (n < 40) return TONE_HEX.danger;
  if (n < 70) return TONE_HEX.warning;
  return TONE_HEX.success;
}
