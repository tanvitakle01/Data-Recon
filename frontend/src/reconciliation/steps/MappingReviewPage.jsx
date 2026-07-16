// Mapping Review — reached from Step 4's "Run Deterministic Mapping" button.
// NOT one of the wizard's 6 numbered steps: it never touches state.step, so
// the stepper keeps showing Step 4 "Rules" as current throughout. Read/review
// only — no inline editing or manual override (future scope).
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useWizard } from "../context/useWizard";
import { WizardActions } from "../context/wizardReducer";

const TIER_LABEL = {
  very_high: "VERY_HIGH",
  high: "HIGH",
  medium: "MEDIUM",
  none: "NONE",
  out_of_scope: "OUT_OF_SCOPE",
};

const TIER_ORDER = ["very_high", "high", "medium", "out_of_scope", "none"];

function TierBadge({ tier }) {
  return <span className={`tier-badge tier-badge--${tier}`}>{TIER_LABEL[tier] ?? tier}</span>;
}

function tierCounts(matches) {
  const counts = { very_high: 0, high: 0, medium: 0, out_of_scope: 0, none: 0 };
  for (const m of matches ?? []) {
    if (counts[m.confidence] !== undefined) counts[m.confidence] += 1;
  }
  return counts;
}

// One field pair's review section: tier summary, All/tier/Unmapped/Excluded
// filter tabs, and the full distinct-source-value table.
function FieldMappingSection({ title, mapping }) {
  const [tab, setTab] = useState("all");
  const matches = useMemo(() => mapping?.matches ?? [], [mapping]);
  const counts = useMemo(() => tierCounts(matches), [matches]);

  const filtered = useMemo(() => {
    if (tab === "unmapped") return matches.filter((m) => m.confidence === "none");
    if (tab === "excluded") return matches.filter((m) => m.confidence === "out_of_scope");
    if (tab === "very_high" || tab === "high" || tab === "medium" || tab === "none") {
      return matches.filter((m) => m.confidence === tab);
    }
    return matches;
  }, [matches, tab]);

  if (!mapping) {
    return (
      <section className="wizard-section">
        <h3 className="wizard-section__title">{title}</h3>
        <p className="wizard-field__help">No result for this field pair.</p>
      </section>
    );
  }

  return (
    <section className="wizard-section">
      <h3 className="wizard-section__title">
        {title}: {mapping.source_field} → {mapping.target_field}
      </h3>
      <div className="contract-summary">
        {TIER_ORDER.map((tier) => (
          <span key={tier} className="contract-summary__chip">
            {TIER_LABEL[tier]}: {counts[tier]}
          </span>
        ))}
      </div>

      <div className="mapping-review__tabs">
        {[
          ["all", `All (${matches.length})`],
          ["very_high", `VERY_HIGH (${counts.very_high})`],
          ["high", `HIGH (${counts.high})`],
          ["medium", `MEDIUM (${counts.medium})`],
          ["none", `NONE (${counts.none})`],
          ["unmapped", `Unmapped (${counts.none})`],
          ["excluded", `Excluded from scope (${counts.out_of_scope})`],
        ].map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={`mapping-review__tab${tab === key ? " mapping-review__tab--active" : ""}`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "excluded" && (
        <p className="wizard-field__help">
          Excluded from scope — these source values fall outside the target's finished-goods scope and are
          not reconciled. They are not gaps, so they're kept separate from "Unmapped".
        </p>
      )}
      {tab === "unmapped" && (
        <p className="wizard-field__help">
          No deterministic rule matched these source values. They are held out of the shadow dataset with
          a recorded reason — never silently dropped or guessed.
        </p>
      )}

      <div className="surface-elevated mapping-editor__table-wrap">
        <table className="table-elevated mapping-editor__table">
          <thead>
            <tr>
              <th>Source Value</th>
              <th>Matched Target Value</th>
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
    </section>
  );
}

function MappingReviewPage() {
  const { state, dispatch } = useWizard();
  const navigate = useNavigate();
  const { valueMappings, valueMappingsApproved } = state.transformationSpec;

  const backToRules = () => navigate("/reconciliation/transformation-spec");

  if (!valueMappings) {
    return (
      <section className="wizard-step">
        <header className="wizard-step__header">
          <p className="wizard-step__eyebrow">Rules — Mapping Review</p>
          <h2 className="wizard-step__title">Mapping Review</h2>
          <p className="wizard-step__desc">Run Deterministic Mapping on the Rules step first.</p>
        </header>
        <div className="wizard-step__body">
          <p className="wizard-field__help">
            No deterministic value mapping has been run yet. Go back to the Rules step and click
            "Run Deterministic Mapping" once the required field mappings are confirmed.
          </p>
        </div>
        <footer className="wizard-step__footer">
          <button type="button" className="wizard-btn wizard-btn--ghost" onClick={backToRules}>
            Back to Rules
          </button>
        </footer>
      </section>
    );
  }

  const approveAndContinue = () => {
    dispatch({ type: WizardActions.SET_VALUE_MAPPINGS_APPROVAL, approved: true });
    navigate("/reconciliation/transformation-spec");
  };

  return (
    <section className="wizard-step">
      <header className="wizard-step__header">
        <p className="wizard-step__eyebrow">Rules — Mapping Review</p>
        <h2 className="wizard-step__title">Mapping Review</h2>
        
      </header>

      <div className="wizard-step__body">
        <FieldMappingSection title="Material" mapping={valueMappings.product} />
        <FieldMappingSection title="Plant" mapping={valueMappings.location} />
      </div>

      <footer className="wizard-step__footer">
        <button type="button" className="wizard-btn wizard-btn--ghost" onClick={backToRules}>
          Back to Rules
        </button>
        <button type="button" className="wizard-btn wizard-btn--primary" onClick={approveAndContinue}>
          {valueMappingsApproved ? "✓ Approved — Continue" : "Approve & Continue"}
        </button>
      </footer>
    </section>
  );
}

export default MappingReviewPage;
