// Secondary, collapsible subsection inside an entity card: the MDT auxiliary
// *evidence* attributes auto-detected from the fetched data. These strengthen
// the deterministic matcher's rules ONLY — they never enter the business key,
// compare fields, the shadow source, or reconciliation output (see the matching
// engine notes). Rendered here so a reviewer can see which fields were detected,
// their fill rate, and whether a current rule actually consumes them.
//
// This mirrors AuxiliaryFieldsPanel's data contract but is scoped to a single
// entity (its source + target aux groups) and is collapsed by default so the
// entity card leads with the mapping itself, not the evidence plumbing.
import { useId, useState } from "react";
import { Badge } from "@bristlecone/canopy";
import { AUX_GROUP_LABEL } from "../lib/mappingEntities";
import Chevron from "./Chevron";

function auxStatus(c) {
  if (!c.confirmed_existing) return { label: "Absent", variant: "default", cls: "aux--absent" };
  if (!c.confirmed_populated)
    return { label: "Empty (0% filled)", variant: "warning", cls: "aux--empty" };
  return { label: "Confirmed", variant: "success", cls: "aux--ok" };
}

function groupBy(fields) {
  const map = new Map();
  for (const f of fields) {
    if (!map.has(f.group)) map.set(f.group, []);
    map.get(f.group).push(f);
  }
  return [...map.entries()];
}

function AuxiliaryEvidenceSection({ auxFields }) {
  const [open, setOpen] = useState(false);
  const bodyId = useId();

  if (!auxFields || auxFields.length === 0) return null;
  const groups = groupBy(auxFields);

  return (
    <section className={`mr-sub${open ? " is-open" : ""}`}>
      <button
        type="button"
        className="mr-sub__header"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((v) => !v)}
      >
        <Chevron className="mr-sub__chev" open={open} />
        <span className="mr-sub__title">Auxiliary Evidence Attributes</span>
        <span className="mr-sub__count">{auxFields.length}</span>
        <span className="mr-sub__hint">Evidence only — never reconciliation data</span>
      </button>

      <div className="mr-collapse" id={bodyId} role="region" hidden={!open}>
        <div className="mr-collapse__inner">
          <div className="mr-sub__body">
            {groups.map(([group, list]) => (
              <div key={group} className="aux-group">
                <h5 className="aux-group__title">{AUX_GROUP_LABEL[group] ?? group}</h5>
                <div className="surface-elevated mapping-editor__table-wrap">
                  <table className="table-elevated mapping-editor__table">
                    <thead>
                      <tr>
                        <th>Attribute Name</th>
                        <th>Tier</th>
                        <th>Status</th>
                        <th>Fill Rate</th>
                        <th>Used by Rule</th>
                      </tr>
                    </thead>
                    <tbody>
                      {list.map((c) => {
                        const status = auxStatus(c);
                        const usable = c.confirmed_existing && c.confirmed_populated;
                        return (
                          <tr key={`${group}-${c.seed_name}`} className={status.cls}>
                            <td>
                              {c.resolved_name ?? c.seed_name}
                              {c.resolved_name && c.resolved_name !== c.seed_name && (
                                <span className="wizard-field__help"> (seed: {c.seed_name})</span>
                              )}
                            </td>
                            <td>
                              <Badge variant="default">Tier {c.tier}</Badge>
                            </td>
                            <td>
                              <Badge variant={status.variant}>{status.label}</Badge>
                            </td>
                            <td>
                              {c.fill_rate == null ? "—" : `${Math.round(c.fill_rate * 100)}%`}
                            </td>
                            <td>
                              {c.consumed && usable ? (
                                <Badge variant="success">Yes — evidence input</Badge>
                              ) : c.consumed ? (
                                <span className="wizard-field__help">
                                  Rule exists, but not populated
                                </span>
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
          </div>
        </div>
      </div>
    </section>
  );
}

export default AuxiliaryEvidenceSection;
