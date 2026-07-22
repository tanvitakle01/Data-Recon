// One collapsible entity in the Mapping Review accordion (e.g. Material →
// Product, ProductionPlant → Location). The header always shows the source and
// target entity names plus the per-tier mapping statistics; the body — revealed
// on expand — shows the confidence summary, filter tabs, the full distinct
// source-value candidate table, and a nested "Auxiliary Evidence Attributes"
// subsection.
//
// Open state is local so each card toggles independently (only Product opens by
// default per config). The card is intentionally structured so future MDT
// Library sections (approved mappings, MDT fields, evidence rules, confidence
// history, user approvals) can be added as additional body blocks without
// touching the header/summary contract — the entity object already carries an
// `mdt` slot for them.
import { useMemo, useState } from "react";
import { Badge, Tabs } from "@bristlecone/canopy";
import { TIER_BADGE_VARIANT } from "../lib/badgeVariants";
import { TIER_LABEL, TIER_ORDER, ENTITY_FILTERS } from "../lib/mappingEntities";
import AuxiliaryEvidenceSection from "./AuxiliaryEvidenceSection";
import Chevron from "./Chevron";

function TierBadge({ tier }) {
  return (
    <Badge variant={TIER_BADGE_VARIANT[tier] ?? "default"}>{TIER_LABEL[tier] ?? tier}</Badge>
  );
}

function pct(n) {
  return `${Math.round(n * 100)}%`;
}

function EntityMappingCard({ entity }) {
  const [open, setOpen] = useState(Boolean(entity.defaultExpanded));
  const [tab, setTab] = useState("all");
  const { mapping, matches, counts, coverage, mapped, unmapped, excluded, inScope, status } = entity;

  const filtered = useMemo(() => {
    const def = ENTITY_FILTERS.find((f) => f.id === tab);
    if (!def || def.tier == null) return matches;
    return matches.filter((m) => m.confidence === def.tier);
  }, [matches, tab]);

  const filterItems = ENTITY_FILTERS.map((f) => ({
    id: f.id,
    label: `${f.label} (${f.tier == null ? matches.length : counts[f.tier]})`,
  }));

  return (
    <section className={`mr-entity${open ? " is-open" : ""}`}>
      <button
        type="button"
        className="mr-entity__header"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <Chevron open={open} className="mr-entity__chev" />

        <span className="mr-entity__titles">
          <span className="mr-entity__route">
            <span className="mr-entity__ent">{entity.sourceEntity}</span>
            <span className="mr-entity__arrow" aria-hidden="true">
              →
            </span>
            <span className="mr-entity__ent">{entity.targetEntity}</span>
          </span>
          <span className="mr-entity__sub">
            {mapping.source_field} → {mapping.target_field} · {mapping.matches?.length ?? 0} distinct
            source values
          </span>
        </span>

        <span className="mr-entity__stats" aria-hidden="true">
          {TIER_ORDER.map((tier) => (
            <span key={tier} className={`mr-stat mr-stat--${tier}`} title={TIER_LABEL[tier]}>
              <span className="mr-stat__k">{TIER_LABEL[tier]}</span>
              <span className="mr-stat__v">{counts[tier]}</span>
            </span>
          ))}
        </span>

        <Badge className="mr-entity__status" variant={status.variant}>
          {status.label}
        </Badge>
      </button>

      <div className="mr-collapse" role="region" hidden={!open}>
        <div className="mr-collapse__inner">
          <div className="mr-entity__body">
            {/* Confidence summary */}
            <div className="mr-conf">
              <div className="mr-kpi">
                <span className="mr-kpi__v">{pct(coverage)}</span>
                <span className="mr-kpi__k">Coverage (in-scope)</span>
              </div>
              <div className="mr-kpi">
                <span className="mr-kpi__v">{mapped}</span>
                <span className="mr-kpi__k">Mapped</span>
              </div>
              <div className="mr-kpi">
                <span className="mr-kpi__v mr-kpi__v--warn">{unmapped}</span>
                <span className="mr-kpi__k">Unmapped</span>
              </div>
              <div className="mr-kpi">
                <span className="mr-kpi__v">{excluded}</span>
                <span className="mr-kpi__k">Excluded</span>
              </div>
              <div className="mr-kpi">
                <span className="mr-kpi__v">{inScope}</span>
                <span className="mr-kpi__k">In scope</span>
              </div>
            </div>

            <div className="contract-summary section-tier-strip">
              {TIER_ORDER.map((tier) => (
                <Badge key={tier} variant={TIER_BADGE_VARIANT[tier] ?? "default"}>
                  {TIER_LABEL[tier]}: {counts[tier]}
                </Badge>
              ))}
            </div>

            {/* Filters */}
            <Tabs
              className="mapping-review__tabs"
              variant="pills"
              value={tab}
              onChange={setTab}
              items={filterItems}
            />

            {tab === "out_of_scope" && (
              <p className="wizard-field__help">
                Excluded from scope — these source values fall outside the target's finished-goods
                scope and are not reconciled. They are not gaps, so they're kept separate from
                "Unmapped".
              </p>
            )}
            {tab === "none" && (
              <p className="wizard-field__help">
                No deterministic rule matched these source values. They are held out of the shadow
                dataset with a recorded reason — never silently dropped or guessed.
              </p>
            )}

            {/* Mapping candidate table */}
            <div className="surface-elevated mapping-editor__table-wrap">
              <table className="table-elevated mapping-editor__table">
                <thead>
                  <tr>
                    <th>Source Value</th>
                    <th>Target Value</th>
                    <th>Tier</th>
                    <th>Rule</th>
                    <th>Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((m, i) => (
                    <tr
                      key={`${m.source_value}-${i}`}
                      className={m.candidates?.length ? "mapping-review__ambiguous-row" : undefined}
                    >
                      <td>{m.source_value}</td>
                      <td>{m.target_value ?? "— unmapped —"}</td>
                      <td>
                        <TierBadge tier={m.confidence} />
                      </td>
                      <td className="run-meta__mono">{m.rule}</td>
                      <td>
                        {m.evidence}
                        {m.candidates?.length > 0 && (
                          <ul className="mapping-review__candidates">
                            {m.candidates.map((c) => (
                              <li key={c}>Candidate: {c}</li>
                            ))}
                          </ul>
                        )}
                      </td>
                    </tr>
                  ))}
                  {filtered.length === 0 && (
                    <tr>
                      <td colSpan={5} className="wizard-field__help">
                        No rows in this view.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* Secondary collapsible subsection */}
            <AuxiliaryEvidenceSection auxFields={entity.auxFields} />
          </div>
        </div>
      </div>
    </section>
  );
}

export default EntityMappingCard;
