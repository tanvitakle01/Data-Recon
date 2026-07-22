import { Badge } from "@bristlecone/canopy";

// "Recommended for Deterministic Mapping" — auto-detected evidence attributes.
// These are matching-evidence ONLY: they feed the deterministic product/location
// rules and NEVER enter business_key, compare_fields, the shadow source, or
// reconciliation output. Shown so the human can see which fields were detected
// and their fill rate. A field a current rule doesn't yet consume is tagged so
// we never imply it affects matching.
//
// Rendered in two places: the Data/Target Preview (off a connector fetch's
// auxiliary_fields) and the Mapping Review page (off the value-mapping run).
// Deliberately NOT rendered in the primary field-mapping table (Mapping Card /
// MappingEditor) — that table is business_key/compare_fields destined for
// reconciliation, and MDT auxiliary fields must never appear there.

const AUX_GROUP_LABEL = {
  target_product: "Target · Product (IBP)",
  target_location: "Target · Location (IBP)",
  source_product: "Source · Product (S/4)",
  source_plant: "Source · Plant (S/4)",
};

function auxStatus(c) {
  if (!c.confirmed_existing) return { label: "Absent", cls: "aux--absent" };
  if (!c.confirmed_populated) return { label: "Empty (0% filled)", cls: "aux--empty" };
  return { label: "Confirmed", cls: "aux--ok" };
}

function AuxiliaryFieldsPanel({ auxiliaryFields, compact = false }) {
  if (!auxiliaryFields) return null;
  const groups = Object.entries(auxiliaryFields).filter(([, list]) => (list ?? []).length > 0);
  if (groups.length === 0) return null;

  return (
    <section
      className={
        compact
          ? "aux-panel aux-panel--compact"
          : "wizard-section section-shade section-shade--mid"
      }
    >
      <h3 className={compact ? "aux-panel__title" : "wizard-section__title"}>
        Recommended for Deterministic Mapping
      </h3>
      <p className="wizard-field__help">
        Auxiliary evidence attributes auto-detected from the fetched data (existence + fill-rate
        checked). They strengthen the deterministic matcher's rules only — they never appear in the
        business key, compare fields, the shadow source, or reconciliation output.
      </p>
      {groups.map(([groupKey, list]) => (
        <div key={groupKey} className="aux-group">
          <h4 className="aux-group__title">{AUX_GROUP_LABEL[groupKey] ?? groupKey}</h4>
          <div className="surface-elevated mapping-editor__table-wrap">
            <table className="table-elevated mapping-editor__table">
              <thead>
                <tr>
                  <th>Attribute</th>
                  <th>Tier</th>
                  <th>Status</th>
                  <th>Fill rate</th>
                  <th>Used by a rule?</th>
                </tr>
              </thead>
              <tbody>
                {list.map((c) => {
                  const status = auxStatus(c);
                  const usable = c.confirmed_existing && c.confirmed_populated;
                  return (
                    <tr key={c.seed_name} className={status.cls}>
                      <td>
                        {c.resolved_name ?? c.seed_name}
                        {c.resolved_name && c.resolved_name !== c.seed_name && (
                          <span className="wizard-field__help"> (seed: {c.seed_name})</span>
                        )}
                      </td>
                      <td>
                        <Badge variant="default">Tier {c.tier}</Badge>
                      </td>
                      <td>{status.label}</td>
                      <td>{c.fill_rate == null ? "—" : `${Math.round(c.fill_rate * 100)}%`}</td>
                      <td>
                        {c.consumed && usable ? (
                          <Badge variant="success">Yes — evidence input</Badge>
                        ) : c.consumed ? (
                          <span className="wizard-field__help">Rule exists, but not populated</span>
                        ) : (
                          <span className="wizard-field__help">Recommended (no rule yet)</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </section>
  );
}

export default AuxiliaryFieldsPanel;
