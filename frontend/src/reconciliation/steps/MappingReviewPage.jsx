// Mapping Review — reached from the Mapping step's "Open mapping review"
// button on the Deterministic (AI-mapping) flow. NOT one of the 5 numbered
// wizard steps: it never touches state.step, so the stepper keeps showing
// Step 4 "Mapping" as current throughout.
//
// Layout, top to bottom: (1) a KPI strip (distinct values / paired / unpaired
// / awaiting approval, computed across both field pairs), (2) one search box
// that finds a value across BOTH field pairs' columns at once with
// Excel/document "Find" semantics (Enter / search-icon = jump to next match,
// wrapping), (3) one combined "Paired values" card and one combined
// "Unpaired values" card spanning both field pairs — always visible, no
// accordion.
//
// Shows this run's value-pairing results: paired values (identity match,
// library-approved reuse, or a freshly LLM-proposed-and-verified transform)
// with a Transform detail toggle, and unpaired values with the reason
// (including why a claimed pairing was rejected by verification).
// Freshly-verified LLM pairs (rule "value_pairing.llm_verified") carry a
// `library_id` and get an inline Approve/Reject action — that decision only
// controls reuse by FUTURE runs (POST /api/recon/value-pairs/{id}/approve|
// reject); it never blocks THIS run, which already applied the verified pair
// to the shadow source per the existing HIGH-confidence auto-apply policy.
// Decisions live here (lifted out of the old per-section component) purely so
// the "Awaiting approval" KPI reflects them in real time.
//
// No changes to pairing data, verification logic, or confidence scoring here
// — this file is layout and search interaction only.
import { useCallback, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useWizard } from "../context/useWizard";
import { Button, Badge, EmptyState } from "@bristlecone/canopy";
import { Search } from "lucide-react";
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

// Collapsed-by-default: `PL5006@S67900 › prepend "PL", append "@S67900"`. Kept
// as a toggle (not "minimal clicks" territory — this is per-row supplementary
// evidence, not information the review itself depends on).
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
// value-mapping "match" record, tagged with which field pair it belongs to —
// used to build one combined table across both pairs instead of two separate
// sections.
function splitMatches(mapping, pairLabel) {
  const matches = (mapping?.matches ?? []).map((m) => ({ ...m, pairLabel }));
  const paired = matches.filter((m) => m.target_value != null);
  const unpaired = matches.filter((m) => m.target_value == null);
  return { matches, paired, unpaired };
}

function pairLabelFor(mapping, fallback) {
  if (!mapping) return fallback;
  return `${mapping.source_field} → ${mapping.target_field}`;
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

function PairedRow({ match, decision, busy, onDecision, rowState, rowRef }) {
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
      <td className="mono">{match.pairLabel}</td>
      <td className="mono">{match.source_value}</td>
      <td className="mono">
        {match.target_value}
        {siblings.length > 0 && (
          <p className="mapping-review__detail-text">Also candidate for: {siblings.join(", ")}</p>
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
      <td style={{ textAlign: "right" }}>
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

// Real, data-derived classification (no fabricated categories): a value with
// candidates was ambiguous (several equally-accepted matches, none chosen);
// with none, nothing on the target side could be derived at all.
function UnpairedRow({ match, rowState, rowRef }) {
  const ambiguous = match.candidates?.length > 0;
  const rowClass =
    rowState === "active"
      ? "mapping-review__row--active-match"
      : rowState === "match"
        ? "mapping-review__row--match"
        : ambiguous
          ? "mapping-review__ambiguous-row"
          : undefined;
  return (
    <tr ref={rowRef} className={rowClass}>
      <td className="mono">{match.pairLabel}</td>
      <td className="mono">{match.source_value}</td>
      <td>
        <Badge variant={ambiguous ? "warning" : "error"}>{ambiguous ? "Ambiguous" : "No candidate"}</Badge>
      </td>
      <td>
        {match.evidence}
        {ambiguous && (
          <ul className="mapping-review__candidates">
            {match.candidates.map((c) => (
              <li key={c}>Candidate: {c}</li>
            ))}
          </ul>
        )}
      </td>
    </tr>
  );
}

function MappingReviewPage() {
  const { state } = useWizard();
  const navigate = useNavigate();
  const { valueMappings } = state.transformationSpec;

  const backToMapping = () => navigate("/reconciliation/transformation-spec");

  // ── Approve/reject decisions: lifted here (not per-section) so the
  // "Awaiting approval" KPI reflects them live. ────────────────────────────
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

  // ── Combined rows across both field pairs — hooks must run unconditionally,
  // so this lives above the `!valueMappings` early return below even though it
  // renders nothing until data exists. ─────────────────────────────────────
  const productLabel = pairLabelFor(valueMappings?.product, "Material pair");
  const locationLabel = pairLabelFor(valueMappings?.location, "Plant pair");
  const productSplit = useMemo(
    () => splitMatches(valueMappings?.product, productLabel),
    [valueMappings, productLabel]
  );
  const locationSplit = useMemo(
    () => splitMatches(valueMappings?.location, locationLabel),
    [valueMappings, locationLabel]
  );
  const allPaired = useMemo(
    () => [...productSplit.paired, ...locationSplit.paired],
    [productSplit, locationSplit]
  );
  const allUnpaired = useMemo(
    () => [...productSplit.unpaired, ...locationSplit.unpaired],
    [productSplit, locationSplit]
  );

  const kpis = useMemo(() => {
    const total = allPaired.length + allUnpaired.length;
    const awaiting = [...productSplit.matches, ...locationSplit.matches].filter(
      (m) => m.rule === "value_pairing.llm_verified" && m.library_id && !decisions[m.library_id]
    ).length;
    return { total, paired: allPaired.length, unpaired: allUnpaired.length, awaiting };
  }, [allPaired, allUnpaired, productSplit.matches, locationSplit.matches, decisions]);

  // One flat, document-ordered (paired before unpaired) list of every
  // searchable row — this order is what "first match" / "next match" wraps
  // over, and what the jump-to-row scroll targets.
  const flatRows = useMemo(() => {
    const rows = [];
    allPaired.forEach((m, i) => rows.push({ id: `paired-${i}`, match: m }));
    allUnpaired.forEach((m, i) => rows.push({ id: `unpaired-${i}`, match: m }));
    return rows;
  }, [allPaired, allUnpaired]);

  const [query, setQuery] = useState("");
  const [activePos, setActivePos] = useState(-1);
  const rowNodes = useRef(new Map()); // row id -> <tr> DOM node

  const normalizedQuery = query.trim().toLowerCase();

  const matches = useMemo(() => {
    if (!normalizedQuery) return [];
    return flatRows.filter(({ match }) => {
      const source = String(match.source_value ?? "").toLowerCase();
      const target = String(match.target_value ?? "").toLowerCase();
      return source.includes(normalizedQuery) || target.includes(normalizedQuery);
    });
  }, [flatRows, normalizedQuery]);

  // A changed query invalidates the current position — the next Enter/click
  // jumps to the FIRST match of the new query, per Find semantics.
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

  const handleFind = useCallback(() => {
    if (!matches.length) return;
    const next = activePos < 0 ? 0 : (activePos + 1) % matches.length;
    setActivePos(next);
    const target = matches[next];
    if (target) {
      requestAnimationFrame(() => {
        rowNodes.current.get(target.id)?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    }
  }, [matches, activePos]);

  if (!valueMappings) {
    return (
      <section className="wizard-step">
        <header className="wizard-step__header">
          <p className="wizard-step__eyebrow">Mapping — Mapping Review</p>
          <h2 className="wizard-step__title">Mapping Review</h2>
          <p className="wizard-step__desc">Run AI-mapping on the Mapping step first.</p>
        </header>
        <div className="wizard-step__body">
          <EmptyState
            title="No mapping review yet"
            description={'No value pairing has been run yet. Go back to the Mapping step and click "Run AI-mapping" once the required field mappings are confirmed.'}
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

      <div className="wizard-step__body ct-col">
        <div className="ct-kpi-grid">
          <div className="ct-kpi-card">
            <p className="ct-kpi-card__label">Distinct values</p>
            <div className="ct-kpi-card__row">
              <span className="ct-kpi-card__value">{kpis.total}</span>
              <span className="ct-kpi-card__sub">in scope</span>
            </div>
          </div>
          <div className="ct-kpi-card">
            <p className="ct-kpi-card__label">Paired</p>
            <div className="ct-kpi-card__row">
              <span className="ct-kpi-card__value" style={{ color: "var(--match)" }}>
                {kpis.paired}
              </span>
              <span className="ct-kpi-card__sub">
                {kpis.total ? `${Math.round((kpis.paired / kpis.total) * 100)}%` : "—"}
              </span>
            </div>
          </div>
          <div className="ct-kpi-card">
            <p className="ct-kpi-card__label">Unpaired</p>
            <div className="ct-kpi-card__row">
              <span className="ct-kpi-card__value" style={{ color: "var(--missing)" }}>
                {kpis.unpaired}
              </span>
              <span className="ct-kpi-card__sub">become mismatches</span>
            </div>
          </div>
          <div className="ct-kpi-card">
            <p className="ct-kpi-card__label">Awaiting approval</p>
            <div className="ct-kpi-card__row">
              <span className="ct-kpi-card__value" style={{ color: "var(--bcone-orange)" }}>
                {kpis.awaiting}
              </span>
              <span className="ct-kpi-card__sub">for future reuse</span>
            </div>
          </div>
        </div>

        <SearchBar
          query={query}
          onQueryChange={handleQueryChange}
          onFind={handleFind}
          matchCount={matches.length}
          activePos={activePos}
        />

        {actionError && <p className="wizard-field__help">{actionError}</p>}

        <section className="ct-card">
          <div className="ct-card__head">
            <h3 className="ct-card__title">Paired values</h3>
          </div>
          <div className="ct-table-wrap">
            <table className="ct-table">
              <thead>
                <tr>
                  <th>Field pair</th>
                  <th>Source value</th>
                  <th>Target value</th>
                  <th>Origin</th>
                  <th>Dates</th>
                  <th>Transform</th>
                  <th style={{ textAlign: "right" }}>Reuse</th>
                </tr>
              </thead>
              <tbody>
                {allPaired.map((m, i) => {
                  const id = `paired-${i}`;
                  return (
                    <PairedRow
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
                {allPaired.length === 0 && (
                  <tr>
                    <td colSpan={7} className="wizard-field__help">
                      No values paired yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="ct-card">
          <div className="ct-card__head">
            <h3 className="ct-card__title">Unpaired values</h3>
            {allUnpaired.length > 0 && <Badge variant="error">{allUnpaired.length}</Badge>}
            <span className="ct-card__spacer" />
            <span className="ct-card__hint">Each unpaired value becomes a reported mismatch</span>
          </div>
          <div className="ct-table-wrap">
            <table className="ct-table">
              <thead>
                <tr>
                  <th>Field pair</th>
                  <th>Source value</th>
                  <th>Reason</th>
                  <th>What it means</th>
                </tr>
              </thead>
              <tbody>
                {allUnpaired.map((m, i) => {
                  const id = `unpaired-${i}`;
                  return (
                    <UnpairedRow key={id} match={m} rowState={getRowState(id)} rowRef={registerRowRef(id)} />
                  );
                })}
                {allUnpaired.length === 0 && (
                  <tr>
                    <td colSpan={4} className="wizard-field__help">
                      Every value paired.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
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
