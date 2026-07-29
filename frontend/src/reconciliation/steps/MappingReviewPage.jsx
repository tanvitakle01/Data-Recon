// Mapping Review — reached from the Mapping step's "View Mapping Review"
// button on the Deterministic flow. NOT one of the 5 numbered wizard steps: it
// never touches state.step, so the stepper keeps showing Step 4 "Mapping" as
// current throughout.
//
// Layout, top to bottom: (1) two small pie charts summarizing matched vs.
// unmatched counts per field pair, (2) one search box that finds a value
// across BOTH field pairs' Material/PRDID/Plant/LOCID columns at once with
// Excel/document "Find" semantics (Enter / search-icon = jump to next match,
// wrapping), (3) the two field-pairing sections themselves, each collapsible
// (collapsed by default) and auto-expanded when a search match lands inside.
//
// Shows this run's value-pairing results: paired values (identity match,
// library-approved reuse, or a freshly LLM-proposed-and-verified transform)
// with a collapsed-by-default transform detail, and unpaired values with the
// reason (including why a claimed pairing was rejected by verification).
// Freshly-verified LLM pairs (rule "value_pairing.llm_verified") carry a
// `library_id` and get an inline Approve/Reject action — that decision only
// controls reuse by FUTURE runs (POST /api/recon/value-pairs/{id}/approve|
// reject); it never blocks THIS run, which already applied the verified pair
// to the shadow source per the existing HIGH-confidence auto-apply policy.
//
// No changes to pairing data, verification logic, or confidence scoring here
// — this file is layout and search interaction only.
import { useCallback, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useWizard } from "../context/useWizard";
import { Button, Badge, EmptyState, CollapsibleSection } from "@bristlecone/canopy";
import { Search } from "lucide-react";
import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";
import { TIER_BADGE_VARIANT } from "../lib/badgeVariants";
import api from "../../services/api";

const TIER_LABEL = {
  very_high: "Identity",
  high: "Verified",
};

function TierBadge({ tier }) {
  return <Badge variant={TIER_BADGE_VARIANT[tier] ?? "default"}>{TIER_LABEL[tier] ?? tier}</Badge>;
}

// A ranking/labeling hint only — never a filter (see value_pairing.pipeline).
// `true` = dates overlap (positive signal), `false` = checked, no overlap,
// `null`/`undefined` = no signal (sole candidate, or no parseable dates).
function CorroborationBadge({ corroboration }) {
  if (corroboration === true) {
    return <Badge variant="success">Dates overlap</Badge>;
  }
  if (corroboration === false) {
    return <Badge variant="warning">No date overlap</Badge>;
  }
  return <Badge variant="default">No signal</Badge>;
}

// Collapsed-by-default: `PL5006@S67900 › prepend "PL", append "@S67900"`.
function TransformDetail({ evidence }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        className="mapping-review__detail-toggle"
        onClick={() => setOpen((o) => !o)}
      >
        {open ? "▾ hide" : "› details"}
      </button>
      {open && <p className="mapping-review__detail-text">{evidence}</p>}
    </div>
  );
}

// A distinct source value split into paired/unpaired matches, one row per
// value-mapping "match" record — used both to render the tables and to build
// the flat, document-ordered search index in MappingReviewPage.
function splitMatches(mapping) {
  const matches = mapping?.matches ?? [];
  const paired = matches.filter((m) => m.target_value != null);
  const unpaired = matches.filter((m) => m.target_value == null);
  return { matches, paired, unpaired };
}

// Distinct-VALUE counts (not row counts) — a source value with two accepted
// candidates (see value_pairing.pipeline) is one matched value, not two.
function summarizeMapping(mapping) {
  const matches = mapping?.matches ?? [];
  const matched = new Set(
    matches.filter((m) => m.target_value != null).map((m) => m.source_value)
  ).size;
  const unmatched = new Set(
    matches.filter((m) => m.target_value == null).map((m) => m.source_value)
  ).size;
  return { matched, unmatched };
}

// Two small pie charts (Material↔PRDID, Plant↔LOCID): matched vs. unmatched.
// Every slice is labeled with its literal count both on the wedge and in the
// caption underneath — colour alone never carries the number.
function MatchSummaryChart({ title, matched, unmatched }) {
  const total = matched + unmatched;
  const data = [
    { name: "Matched", value: matched, color: "var(--match)" },
    { name: "Unmatched", value: unmatched, color: "var(--missing)" },
  ];

  return (
    <div className="mapping-review__chart">
      <div className="mapping-review__chart-title">{title}</div>
      {total === 0 ? (
        <p className="wizard-field__help">No values yet.</p>
      ) : (
        <>
          <div className="mapping-review__chart-figure">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={data}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={36}
                  outerRadius={58}
                  paddingAngle={2}
                  label={({ value }) => value}
                  labelLine={false}
                >
                  {data.map((d) => (
                    <Cell key={d.name} fill={d.color} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="mapping-review__chart-caption">
            <span className="mapping-review__chart-swatch" style={{ background: "var(--match)" }} />
            {matched} matched
            <span className="mapping-review__chart-swatch" style={{ background: "var(--missing)" }} />
            {unmatched} unmatched
          </div>
        </>
      )}
    </div>
  );
}

// One search box covering both field-pairing sections at once — Excel/
// document "Find" semantics: Enter or an icon click jumps to the first match,
// then advances to the next on every subsequent Enter/click, wrapping.
function SearchBar({ query, onQueryChange, onFind, matchCount, activePos }) {
  const handleIconActivate = (e) => {
    if (e.type === "keydown" && e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    onFind();
  };

  let statusText = null;
  if (query.trim()) {
    if (matchCount === 0) {
      statusText = "No matches";
    } else if (activePos < 0) {
      statusText = `${matchCount} match${matchCount === 1 ? "" : "es"} found`;
    } else {
      statusText = `Match ${activePos + 1} of ${matchCount}`;
    }
  }

  return (
    <div className="mapping-review__search-bar">
      <div className="mapping-review__search">
        <Search
          className="mapping-review__search-icon"
          size={16}
          role="button"
          tabIndex={0}
          aria-label="Find next match"
          onClick={onFind}
          onKeyDown={handleIconActivate}
        />
        <input
          type="text"
          className="wizard-input mapping-review__search-input"
          placeholder="Search Material, PRDID, Plant, or LOCID…"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              onFind();
            }
          }}
        />
      </div>
      {statusText && <span className="mapping-review__search-count">{statusText}</span>}
    </div>
  );
}

function PairRow({ match, decision, busy, onDecision, rowState, rowRef }) {
  const reviewable = match.rule === "value_pairing.llm_verified" && match.library_id && !decision;
  // More than one verified candidate for this source value (see
  // value_pairing.pipeline — every candidate is accepted, never forced to a
  // single winner), so this row's own target is one of several siblings.
  const siblings = (match.candidates ?? []).filter((c) => c !== match.target_value);
  const rowClass =
    rowState === "active"
      ? "mapping-review__row--active-match"
      : rowState === "match"
        ? "mapping-review__row--match"
        : undefined;
  return (
    <tr ref={rowRef} className={rowClass}>
      <td>{match.source_value}</td>
      <td>
        {match.target_value}
        {siblings.length > 0 && (
          <p className="mapping-review__detail-text">
            Also candidate for: {siblings.join(", ")}
          </p>
        )}
      </td>
      <td>
        <TierBadge tier={match.confidence} />
      </td>
      <td>
        {siblings.length > 0 ? <CorroborationBadge corroboration={match.corroboration} /> : null}
      </td>
      <td>
        <TransformDetail evidence={match.evidence} />
      </td>
      <td>
        {decision && (
          <span className="mapping-review__decision">
            {decision === "approved" ? "Approved" : "Rejected"}
          </span>
        )}
        {reviewable && (
          <div className="mapping-review__actions">
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => onDecision(match.library_id, "approve")}
            >
              Approve
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => onDecision(match.library_id, "reject")}
            >
              Reject
            </Button>
          </div>
        )}
      </td>
    </tr>
  );
}

// One field pair's review section: paired values (with reviewable transform
// detail) and unpaired values (with the reason a value has no target).
// `paired`/`unpaired` are computed once by the parent (it needs them too, to
// build the cross-section search index) rather than recomputed here.
function FieldPairingSection({
  sectionKey,
  title,
  mapping,
  paired,
  unpaired,
  getRowState,
  registerRowRef,
  forceOpenGen,
}) {
  const [decisions, setDecisions] = useState({}); // library_id -> "approved" | "rejected"
  const [busyId, setBusyId] = useState(null);
  const [actionError, setActionError] = useState(null);

  const decide = async (libraryId, action) => {
    setActionError(null);
    setBusyId(libraryId);
    try {
      await api.post(`/api/recon/value-pairs/${libraryId}/${action}`);
      setDecisions((prev) => ({ ...prev, [libraryId]: action === "approve" ? "approved" : "rejected" }));
    } catch (err) {
      setActionError(`Failed to ${action} this pair: ${err?.message || err}`);
    } finally {
      setBusyId(null);
    }
  };

  if (!mapping) {
    return (
      <section className="wizard-section">
        <h3 className="wizard-section__title">{title}</h3>
        <EmptyState title="No result for this field pair." />
      </section>
    );
  }

  const badge = (
    <div className="contract-summary section-tier-strip">
      <Badge variant="default">Paired: {paired.length}</Badge>
      <Badge variant="default">Unpaired: {unpaired.length}</Badge>
    </div>
  );

  return (
    <CollapsibleSection
      // Remounting with a fresh key when forceOpenGen bumps is how a search
      // match forces this section open — CollapsibleSection only takes an
      // uncontrolled `defaultOpen`, so a key change + defaultOpen=true is how
      // the parent programmatically re-opens it (see MappingReviewPage).
      key={`${sectionKey}-${forceOpenGen}`}
      defaultOpen={forceOpenGen > 0}
      title={`${title}: ${mapping.source_field} → ${mapping.target_field}`}
      badge={badge}
      className="mapping-review__section"
    >
      {actionError && <p className="wizard-field__help">{actionError}</p>}

      <div className="surface-elevated mapping-editor__table-wrap">
        <table className="table-elevated mapping-editor__table">
          <thead>
            <tr>
              <th>Source Value</th>
              <th>Target Value</th>
              <th>Origin</th>
              <th>Corroboration</th>
              <th>Transform</th>
              <th>Review</th>
            </tr>
          </thead>
          <tbody>
            {paired.map((m, i) => {
              const id = `${sectionKey}-paired-${i}`;
              return (
                <PairRow
                  key={id}
                  match={m}
                  decision={m.library_id ? decisions[m.library_id] : undefined}
                  busy={busyId === m.library_id}
                  onDecision={decide}
                  rowState={getRowState(id)}
                  rowRef={registerRowRef(id)}
                />
              );
            })}
            {paired.length === 0 && (
              <tr>
                <td colSpan={6} className="wizard-field__help">
                  No values paired yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <h4 className="mapping-review__subtitle">Unpaired ({unpaired.length})</h4>
      <div className="surface-elevated mapping-editor__table-wrap">
        <table className="table-elevated mapping-editor__table">
          <thead>
            <tr>
              <th>Source Value</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {unpaired.map((m, i) => {
              const id = `${sectionKey}-unpaired-${i}`;
              const rowState = getRowState(id);
              const classes = [
                m.candidates?.length ? "mapping-review__ambiguous-row" : null,
                rowState === "active" ? "mapping-review__row--active-match" : null,
                rowState === "match" ? "mapping-review__row--match" : null,
              ]
                .filter(Boolean)
                .join(" ") || undefined;
              return (
                <tr key={id} ref={registerRowRef(id)} className={classes}>
                  <td>{m.source_value}</td>
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
              );
            })}
            {unpaired.length === 0 && (
              <tr>
                <td colSpan={2} className="wizard-field__help">
                  Every value paired.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </CollapsibleSection>
  );
}

function MappingReviewPage() {
  const { state } = useWizard();
  const navigate = useNavigate();
  const { valueMappings } = state.transformationSpec;

  const backToMapping = () => navigate("/reconciliation/transformation-spec");

  // ── Search across both sections at once (Material/PRDID/Plant/LOCID) ─────
  // Hooks must run unconditionally, so this lives above the `!valueMappings`
  // early return below even though it renders nothing until data exists.
  const productSplit = useMemo(
    () => splitMatches(valueMappings?.product),
    [valueMappings]
  );
  const locationSplit = useMemo(
    () => splitMatches(valueMappings?.location),
    [valueMappings]
  );

  // One flat, document-ordered (product section, then location section; paired
  // before unpaired within each) list of every searchable row — this order is
  // what "first match" / "next match" wraps over.
  const flatRows = useMemo(() => {
    const rows = [];
    const push = (sectionKey, type, list) => {
      list.forEach((m, i) => rows.push({ id: `${sectionKey}-${type}-${i}`, sectionKey, match: m }));
    };
    push("product", "paired", productSplit.paired);
    push("product", "unpaired", productSplit.unpaired);
    push("location", "paired", locationSplit.paired);
    push("location", "unpaired", locationSplit.unpaired);
    return rows;
  }, [productSplit, locationSplit]);

  const [query, setQuery] = useState("");
  const [activePos, setActivePos] = useState(-1);
  const [forceOpen, setForceOpen] = useState({ product: 0, location: 0 });
  const rowNodes = useRef(new Map()); // row id -> <tr> DOM node

  const normalizedQuery = query.trim().toLowerCase();

  // Checks all four fields (Material, PRDID, Plant, LOCID) in one query —
  // whichever pair of source/target names a section actually uses.
  const matches = useMemo(() => {
    if (!normalizedQuery) return [];
    return flatRows.filter(({ match }) => {
      const source = String(match.source_value ?? "").toLowerCase();
      const target = String(match.target_value ?? "").toLowerCase();
      return source.includes(normalizedQuery) || target.includes(normalizedQuery);
    });
  }, [flatRows, normalizedQuery]);

  // A changed query invalidates the current position — the next Enter/click
  // jumps to the FIRST match of the new query, per Find semantics. Reset
  // happens right in the change handler (not a `useEffect`) so it's just a
  // synchronous part of handling the keystroke, not a derived side effect.
  const handleQueryChange = useCallback((value) => {
    setQuery(value);
    setActivePos(-1);
  }, []);

  const matchPositionById = useMemo(() => {
    const map = new Map();
    matches.forEach((m, i) => map.set(m.id, i));
    return map;
  }, [matches]);

  const getRowState = useCallback(
    (id) => {
      if (!normalizedQuery) return undefined;
      const pos = matchPositionById.get(id);
      if (pos === undefined) return undefined;
      return pos === activePos ? "active" : "match";
    },
    [normalizedQuery, matchPositionById, activePos]
  );

  const registerRowRef = useCallback(
    (id) => (node) => {
      if (node) rowNodes.current.set(id, node);
      else rowNodes.current.delete(id);
    },
    []
  );

  // Tracks whether we've already forced a section open this session — a plain
  // ref, not state, so updating it never itself triggers a render. Without
  // this, every "next match" press within an already-open section would bump
  // `forceOpen` and remount the whole CollapsibleSection (see
  // FieldPairingSection's key trick) for no visible benefit, flickering the
  // table. We only need the forced remount the FIRST time a match lands in a
  // given section.
  const openedSections = useRef({ product: false, location: false });

  const jumpTo = useCallback(
    (pos) => {
      const target = matches[pos];
      if (!target) return;
      if (!openedSections.current[target.sectionKey]) {
        openedSections.current[target.sectionKey] = true;
        setForceOpen((prev) => ({ ...prev, [target.sectionKey]: prev[target.sectionKey] + 1 }));
      }
      requestAnimationFrame(() => {
        rowNodes.current.get(target.id)?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    },
    [matches]
  );

  const handleFind = useCallback(() => {
    if (!matches.length) return;
    const next = activePos < 0 ? 0 : (activePos + 1) % matches.length;
    setActivePos(next);
    jumpTo(next);
  }, [matches, activePos, jumpTo]);

  if (!valueMappings) {
    return (
      <section className="wizard-step">
        <header className="wizard-step__header">
          <p className="wizard-step__eyebrow">Mapping — Mapping Review</p>
          <h2 className="wizard-step__title">Mapping Review</h2>
          <p className="wizard-step__desc">Run Deterministic Mapping on the Mapping step first.</p>
        </header>
        <div className="wizard-step__body">
          <EmptyState
            title="No mapping review yet"
            description={'No value pairing has been run yet. Go back to the Mapping step and click "Run Deterministic Mapping" once the required field mappings are confirmed.'}
          />
        </div>
        <footer className="wizard-step__footer">
          <Button type="button" variant="outline" onClick={backToMapping}>
            Back to Mapping
          </Button>
        </footer>
      </section>
    );
  }

  const productSummary = summarizeMapping(valueMappings.product);
  const locationSummary = summarizeMapping(valueMappings.location);

  return (
    <section className="wizard-step wizard-step--canvas">
      <header className="wizard-step__header">
        <p className="wizard-step__eyebrow">Mapping — Mapping Review</p>
        <h2 className="wizard-step__title">Mapping Review</h2>
        <p className="wizard-step__desc">
          Review this run's value-pairing results. A freshly-verified pairing already applied to
          this run — Approve/Reject here only decides whether it's reused automatically next time.
        </p>
      </header>

      <div className="wizard-step__body">
        <div className="mapping-review__summary">
          <MatchSummaryChart
            title="Material ↔ PRDID"
            matched={productSummary.matched}
            unmatched={productSummary.unmatched}
          />
          <MatchSummaryChart
            title="Plant ↔ LOCID"
            matched={locationSummary.matched}
            unmatched={locationSummary.unmatched}
          />
        </div>

        <SearchBar
          query={query}
          onQueryChange={handleQueryChange}
          onFind={handleFind}
          matchCount={matches.length}
          activePos={activePos}
        />

        <FieldPairingSection
          sectionKey="product"
          title="Material"
          mapping={valueMappings.product}
          paired={productSplit.paired}
          unpaired={productSplit.unpaired}
          getRowState={getRowState}
          registerRowRef={registerRowRef}
          forceOpenGen={forceOpen.product}
        />
        <FieldPairingSection
          sectionKey="location"
          title="Plant"
          mapping={valueMappings.location}
          paired={locationSplit.paired}
          unpaired={locationSplit.unpaired}
          getRowState={getRowState}
          registerRowRef={registerRowRef}
          forceOpenGen={forceOpen.location}
        />
      </div>

      <footer className="wizard-step__footer">
        <Button type="button" variant="outline" onClick={backToMapping}>
          Back to Mapping
        </Button>
      </footer>
    </section>
  );
}

export default MappingReviewPage;
