/* ============================================================================
   Semantic status — the LAW. Every screen resolves colors through this map.
   The 8 status keys correspond 1:1 to the Step-2 tokens:
     match     VERY_HIGH / Match          strong green
     high      HIGH                        soft (distinct) green
     medium    MEDIUM                      amber
     mismatch  Quantity Mismatch           distinct orange (never == medium)
     missing   NONE / Missing / Unmapped   muted red
     scope     OUT_OF_SCOPE / Excluded     slate (never red)
     extra     Extra in Target             cyan (distinct from missing)
     info      Informational / Aggregated  blue
   ========================================================================== */

/** Tailwind class bundle per status. `soft` = tinted chip, `solid` = filled. */
export const STATUS_CLASSES = {
  match:    { fg: "text-match-fg",    bg: "bg-match-bg",    bd: "border-match-bd",    solid: "bg-match-solid",    dot: "bg-match-solid" },
  high:     { fg: "text-high-fg",     bg: "bg-high-bg",     bd: "border-high-bd",     solid: "bg-high-solid",     dot: "bg-high-solid" },
  medium:   { fg: "text-medium-fg",   bg: "bg-medium-bg",   bd: "border-medium-bd",   solid: "bg-medium-solid",   dot: "bg-medium-solid" },
  mismatch: { fg: "text-mismatch-fg", bg: "bg-mismatch-bg", bd: "border-mismatch-bd", solid: "bg-mismatch-solid", dot: "bg-mismatch-solid" },
  missing:  { fg: "text-missing-fg",  bg: "bg-missing-bg",  bd: "border-missing-bd",  solid: "bg-missing-solid",  dot: "bg-missing-solid" },
  scope:    { fg: "text-scope-fg",    bg: "bg-scope-bg",    bd: "border-scope-bd",    solid: "bg-scope-solid",    dot: "bg-scope-solid" },
  extra:    { fg: "text-extra-fg",    bg: "bg-extra-bg",    bd: "border-extra-bd",    solid: "bg-extra-solid",    dot: "bg-extra-solid" },
  info:     { fg: "text-info-fg",     bg: "bg-info-bg",     bd: "border-info-bd",     solid: "bg-info-solid",     dot: "bg-info-solid" },
  neutral:  { fg: "text-text-secondary", bg: "bg-surface-2", bd: "border-line-2",     solid: "bg-line-3",         dot: "bg-line-3" },
};

/** Confidence tier enum (backend: value_mapping.py) -> status + label. */
export const TIER = {
  very_high:    { status: "match",  label: "VERY_HIGH" },
  high:         { status: "high",   label: "HIGH" },
  medium:       { status: "medium", label: "MEDIUM" },
  none:         { status: "missing", label: "NONE" },
  out_of_scope: { status: "scope",  label: "OUT_OF_SCOPE" },
};

/** Reconciliation outcome -> status + label. */
export const OUTCOME = {
  match:             { status: "match",    label: "Match" },
  mismatch:          { status: "mismatch", label: "Quantity Mismatch" },
  missing_in_source: { status: "extra",    label: "Missing in Source" },
  missing_in_target: { status: "missing",  label: "Missing in Target" },
  extra_in_target:   { status: "extra",    label: "Extra in Target" },
  exception:         { status: "missing",  label: "Exception" },
};

/** Transformation change kind (shadow diff) -> status + label. */
export const CHANGE = {
  added:      { status: "match",    label: "Added" },
  modified:   { status: "medium",   label: "Modified" },
  removed:    { status: "missing",  label: "Removed" },
  aggregated: { status: "info",     label: "Aggregated" },
  renamed:    { status: "info",     label: "Renamed" },
};

/** Numeric confidence (0..1) -> status. */
export function confidenceStatus(c) {
  if (c >= 0.85) return "match";
  if (c >= 0.7) return "high";
  if (c >= 0.4) return "medium";
  return "missing";
}
