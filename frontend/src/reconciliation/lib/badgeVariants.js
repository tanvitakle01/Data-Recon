// Single source of truth mapping reconciliation domain states -> Canopy Badge
// variants, so the confidence-tier and reconciliation-outcome color language is
// identical on every page. Canopy's Badge variants resolve to its semantic
// --bcone-* tokens (success=green, warning=orange, error=red, info=blue,
// teal, default=gray) — we never hand-pick colors at the call site.

// Confidence tiers. VERY_HIGH uses `teal` so it stays visually distinct from
// HIGH (`success`/green); the rest collapse onto Canopy's status variants.
export const TIER_BADGE_VARIANT = {
  very_high: "teal",
  high: "success",
  medium: "warning",
  none: "error",
  out_of_scope: "default",
};

// Reconciliation outcomes. `extra` uses `cyan` so "Extra in Target" stays
// visually distinct from the blue `info`/aggregated language (preserving the
// old semantic where Extra ≠ Missing ≠ Informational).
export const OUTCOME_BADGE_VARIANT = {
  match: "success",
  mismatch: "error",
  missing: "warning",
  extra: "cyan",
};

// A confidence fraction (0..1) -> variant, matching the old
// ok(>=0.7)/pending(>=0.4)/fail thresholds.
export function confidenceVariant(conf) {
  if (conf >= 0.7) return "success";
  if (conf >= 0.4) return "warning";
  return "error";
}

// Column-change / operation kinds shown as pills in the transformation preview.
export const CHANGE_BADGE_VARIANT = {
  added: "success",
  modified: "warning",
  removed: "error",
  aggregated: "info",
  renamed: "teal",
};
