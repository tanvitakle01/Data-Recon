// Single source of truth for the docs page's section anchors — the sidebar,
// scroll-spy, and prev/next footer links all walk this same flat list so
// they can never drift out of sync with each other.
const SECTIONS = [
  { id: "core-principle", title: "The Core Principle", level: 2 },
  { id: "pipeline-stages", title: "Pipeline Stages", level: 2 },
  { id: "stage-ingestion", title: "1. Ingestion", level: 3 },
  { id: "stage-attribute-mapping", title: "2. Attribute Mapping", level: 3 },
  { id: "stage-key-compare", title: "3. Key / Compare Classification", level: 3 },
  { id: "stage-date-detection", title: "4. Date-Field Identification", level: 3 },
  { id: "stage-batching", title: "5. Date-Aligned Batching", level: 3 },
  { id: "stage-distinct-values", title: "6. Distinct Value Extraction", level: 3 },
  { id: "stage-value-pairing", title: "7. Value Pairing", level: 3 },
  { id: "stage-reconciliation", title: "8. Reconciliation", level: 3 },
  { id: "stage-results-lineage", title: "9. Results + Lineage", level: 3 },
  { id: "quality-gates", title: "Quality Gates", level: 2 },
  { id: "transformation-contract", title: "The Transformation Contract", level: 2 },
  { id: "reuse-learning", title: "Reuse and Learning", level: 2 },
  { id: "known-limits", title: "Known Limits", level: 2 },
];

export default SECTIONS;
