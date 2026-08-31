import { useEffect, useRef, useState } from "react";
import { FiArrowUp } from "react-icons/fi";
import JsonViewer from "../components/JsonViewer";
import DocsSidebar from "../components/docs/DocsSidebar";
import PipelineDiagram from "../components/docs/PipelineDiagram";
import Callout from "../components/docs/Callout";
import SectionFooterNav from "../components/docs/SectionFooterNav";
import SECTIONS from "../components/docs/docsSections";
import styles from "./docsArchitecturePage.module.css";

function StageKind({ llm, children }) {
  return (
    <div className={styles.kindRow}>
      <span className={`${styles.kindPill} ${llm ? styles.kindLlm : styles.kindDet}`}>
        {llm ? "LLM-assisted, then deterministically verified" : "Deterministic"}
      </span>
      {children}
    </div>
  );
}

const REGISTRY_SAMPLE = {
  op: "remove_leading_zeros",
  field: "MATNR",
  params: { min_width: 2 },
};

const CONTRACT_SHAPE = {
  business_key: [{ source_field: "MATNR", target_field: "PRDID" }],
  compare_fields: [{ source_field: "REQ_QTY", target_field: "DEMANDQTY", match_type: "exact" }],
  operations: [
    { op: "trim_string", field: "MATNR", params: {} },
    { op: "remove_leading_zeros", field: "MATNR", params: { min_width: 2 } },
  ],
};

const VERIFY_SAMPLE = `def verify_chain(ops, field, source_value):
    """Re-run the LLM's proposed op chain for real, against the real
    source value. Any failure is a rejection, never a crash."""
    frame = pd.DataFrame({field: [source_value]})
    for step in ops:
        spec = get_operation(step["op"])       # KeyError -> not allow-listed
        errors = spec.validate(field, step["params"], [field])
        if errors:
            return False, "; ".join(errors)
        frame = spec.func(frame, field, step["params"])
    return True, frame[field].iloc[0]`;

function DocsArchitecturePage() {
  const [activeId, setActiveId] = useState(SECTIONS[0].id);
  const [readMinutes, setReadMinutes] = useState(null);
  const [showBackToTop, setShowBackToTop] = useState(false);
  const articleRef = useRef(null);

  useEffect(() => {
    if (articleRef.current) {
      const words = articleRef.current.innerText.trim().split(/\s+/).length;
      setReadMinutes(Math.max(1, Math.round(words / 200)));
    }
  }, []);

  useEffect(() => {
    const headings = SECTIONS.map((s) => document.getElementById(s.id)).filter(Boolean);
    if (!headings.length) return undefined;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible.length > 0) setActiveId(visible[0].target.id);
      },
      { rootMargin: "-96px 0px -70% 0px", threshold: 0 },
    );
    headings.forEach((h) => observer.observe(h));
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const onScroll = () => setShowBackToTop(window.scrollY > 600);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div className={styles.page} id="top">
      <header className={styles.header}>
        <p className={styles.eyebrow}>Architecture Notes</p>
        <h1 className={styles.h1}>The Reconciliation Pipeline</h1>
        <p className={styles.dek}>
          How data moves from a raw source/target extract to a reconciled result — what is
          deterministic, what is LLM-assisted, and the gates that keep the two apart. Written for
          an engineer or SAP consultant evaluating or onboarding onto the tool.
        </p>
        <div className={styles.meta}>
          {readMinutes && <span>{readMinutes} min read</span>}
          <span aria-hidden="true">·</span>
          <span>Sourced from the current codebase — planned or gap items are labeled as such</span>
        </div>
      </header>

      <div className={styles.layout}>
        <DocsSidebar activeId={activeId} />

        <article className={styles.article} ref={articleRef}>
          <section id="core-principle">
            <h2>The Core Principle</h2>
            <p>
              The system's one governing rule, stated in <code>backend/recon_engine/__init__.py</code>:
            </p>
            <blockquote className={styles.sectionIntro}>
              <p>
                <strong>LLM output = Data. Engine output = Execution.</strong> The LLM may only emit a
                structured Transformation Contract (JSON). It never generates or executes code. All
                data transformation and reconciliation is performed by a deterministic engine using a
                fixed, allow-listed operation registry.
              </p>
            </blockquote>
            <p>
              Every value an LLM proposes anywhere in this pipeline reaches reconciliation through one
              of exactly two paths: it is <strong>validated against live system state</strong> before
              use (a field name is checked against the real schema; a business key is confirmed by a
              human before a contract is approved), or it is{" "}
              <strong>mechanically re-executed and verified</strong> before acceptance (a proposed
              transform is replayed through the real allow-listed operation against the real value,
              and rejected on any mismatch). Nothing an LLM asserts reaches reconciliation unchecked.
              The rest of this page traces that guarantee through each pipeline stage — including the
              one place today where the guarantee currently has a gap (see{" "}
              <a href="#known-limits">Known Limits</a>).
            </p>
          </section>

          <section id="pipeline-stages">
            <h2>Pipeline Stages</h2>
            <p>
              A run moves through nine stages. Stages 1–4 build a contract; three gates and (in
              Manual mode) a human approval stand between the compiled contract and execution; stages
              5–7 execute in a loop, once per date-aligned batch; stages 8–9 produce the result.
            </p>
            <PipelineDiagram />

            <h3 id="stage-ingestion">1. Ingestion</h3>
            <StageKind llm={false} />
            <p>
              Source and target data enters as a mapping-sheet-driven upload, a live SAP S/4HANA or
              IBP connector fetch, or a plain Excel/CSV file
              (<code>backend/recon_engine/mapping_sheet_parser.py</code>,{" "}
              <code>backend/routes/s4_metadata.py</code>, <code>backend/routes/ibp_metadata.py</code>).
              The mapping-sheet parser is explicitly documented as{" "}
              <em>&quot;Excel → structured JSON only... NO LLM interpretation&quot;</em> — the same
              workbook always produces the same payload, and every raw source/target extract becomes
              an immutable snapshot that is never modified or written back to the connectors.
            </p>
            <p className={styles.failureMode}>
              <strong>Failure mode:</strong> a column the parser can't classify into any known role
              (source/target/technical field/description/…) is simply carried through as an
              unclassified raw row — it does not block ingestion, but it also won't contribute a
              mapping candidate downstream.
            </p>
            <SectionFooterNav id="stage-ingestion" />

            <h3 id="stage-attribute-mapping">2. Attribute (Field) Mapping</h3>
            <StageKind llm />
            <p>
              An LLM (<code>backend/recon_engine/field_mapper.py::infer_field_mapping</code>) proposes
              column ↔ column pairs from header names and sample values. The result is a
              display/mapping payload only — never applied directly. It lands in the wizard's
              field-mapping table where a human can accept, edit, or override every proposed pair
              before anything downstream reads it.
            </p>
            <p>
              A three-tier resolution order runs before the LLM is even asked: a library lookup
              (exact match on a previously-approved column-set) resolves instantly if this same
              source/target column combination has been mapped before; otherwise the LLM proposes;
              otherwise the human maps manually. See <a href="#reuse-learning">Reuse and Learning</a>.
            </p>
            <p className={styles.failureMode}>
              <strong>Failure mode:</strong> the module is documented to <em>&quot;never raise on LLM
              failure&quot;</em> — an unavailable or failing LLM degrades to an empty/partial proposal,
              leaving the human to map manually rather than blocking the wizard.
            </p>
            <SectionFooterNav id="stage-attribute-mapping" />

            <h3 id="stage-key-compare">3. Key / Compare Classification</h3>
            <StageKind llm />
            <p>
              Which mapped pairs are business keys (identity) versus compared measures (values to
              reconcile) is decided differently depending on mode:
            </p>
            <ul>
              <li>
                <strong>Manual mode:</strong> a human sets <code>business_key</code>/
                <code>compare_fields</code> in the editable mapping table, informed by the field
                mapper's proposed roles. The contract-compiling LLM is contractually forbidden from
                setting these — its system prompt instructs it to always emit them as empty arrays,
                and <code>service.compile_draft()</code> discards anything it puts there regardless,
                attaching the human's confirmed values deterministically instead.
              </li>
              <li>
                <strong>Auto mode:</strong> an LLM identifies the best product and location columns
                on each side (<code>backend/recon_engine/auto_pipeline/candidate_keys.py</code>),
                combined with deterministic date/quantity role detection (name-alias matching, falling
                back to sampling actual values). This becomes <code>business_key</code> /{" "}
                <code>compare_fields</code> directly, and the contract is self-approved (
                <code>approved_by=&quot;auto&quot;</code>) with no human review of this specific choice.
              </li>
            </ul>
            <Callout tone="scope" title="Known limitation">
              <p>
                Auto mode has no human checkpoint on the LLM-influenced business key before approval —
                a code comment in <code>auto_pipeline/nodes.py</code> acknowledges this directly:{" "}
                <em>&quot;Auto mode has no human checkpoint to catch a silently stub-compiled contract
                the way Manual mode's approval step would.&quot;</em> See{" "}
                <a href="#known-limits">Known Limits</a>.
              </p>
            </Callout>
            <p className={styles.failureMode}>
              <strong>Failure mode:</strong> Auto mode hard-stops the run if contract compilation
              degrades to the deterministic stub compiler (no LLM configured, or the LLM call failed)
              rather than silently reconciling on a placeholder contract.
            </p>
            <SectionFooterNav id="stage-key-compare" />

            <h3 id="stage-date-detection">4. Date-Field Identification</h3>
            <StageKind llm={false} />
            <p>
              Whether a column is a date is decided by looking at a sample of its own values — a
              date-shaped regex pre-filter, then a real <code>pandas.to_datetime</code> parse attempt
              (<code>backend/recon_engine/date_detection.py</code>) — never a column-name guess and
              never an LLM call. Date fields are normalized and used for batching and corroboration;
              they are not value-paired like other fields (see stage 5 and stage 7).
            </p>
            <p className={styles.failureMode}>
              <strong>Failure mode:</strong> a column that is mostly-but-not-reliably date-shaped
              (below an 80% sample hit-rate) is treated as <em>not</em> a date — a conservative
              default that avoids misclassifying an ordinary identifier column.
            </p>
            <SectionFooterNav id="stage-date-detection" />

            <h3 id="stage-batching">5. Date-Aligned Batching</h3>
            <StageKind llm={false} />
            <p>
              Before any full row extraction happens, a cheap paginated pull of just the date column
              from both connectors gives the distinct-date union and each date's per-side row count.
              Batches are then cut on record-count thresholds, but{" "}
              <strong>a single date is never split across batches</strong> — every record that could
              possibly match another (date is part of the business key) is guaranteed to land in the
              same batch (<code>backend/recon_engine/auto_pipeline/date_batching.py::plan_batches</code>).
              A date present on only one side still gets its own slot in the union rather than being
              silently dropped.
            </p>
            <p className={styles.failureMode}>
              <strong>Failure mode:</strong> a source/target pair whose date ranges barely overlap
              produces many small, mostly-empty batches rather than failing outright — see{" "}
              <a href="#known-limits">Known Limits</a> on date-window mismatches.
            </p>
            <SectionFooterNav id="stage-batching" />

            <h3 id="stage-distinct-values">6. Distinct Value Extraction</h3>
            <StageKind llm={false} />
            <p>
              For each batch, distinct values of the fields being paired are extracted with blank and
              null values dropped (<code>backend/recon_engine/value_pairing/extraction.py::distinct_values</code>
              ), producing a value-to-count map that feeds the pairing step below.
            </p>
            <SectionFooterNav id="stage-distinct-values" />

            <h3 id="stage-value-pairing">7. Value Pairing</h3>
            <StageKind llm />
            <p>
              This is the stage where an LLM proposal comes closest to reconciliation, and
              correspondingly carries the pipeline's strictest gate. For every distinct value, the
              pipeline tries, in order:
            </p>
            <ol>
              <li>
                <strong>Library lookup</strong> — has this exact value pairing been verified before,
                for this field mapping? If so, reuse it.
              </li>
              <li>
                <strong>Identity pre-pass</strong> — does the source value already exactly match a
                target value? Treated as a <em>candidate</em>, not an auto-accept — an exact string
                match can be coincidental, so it still competes alongside any transform-based
                candidate rather than short-circuiting the search.
              </li>
              <li>
                <strong>LLM residual proposal</strong> — only for values neither step above resolved,
                the LLM proposes an ordered chain of allow-listed operations (e.g.{" "}
                <code>remove_leading_zeros</code> then <code>trim_string</code>) that should transform
                the source value into the target value.
              </li>
              <li>
                <strong>Mandatory deterministic verification</strong> — every proposed chain, from
                every source, is re-executed for real against the real source value before it can
                reach the review UI or the library. This is the pipeline's non-negotiable gate.
              </li>
            </ol>
            <JsonViewer
              className={styles.codeSample}
              language="python"
              filename="backend/recon_engine/value_pairing/verify.py"
              value={VERIFY_SAMPLE}
            />
            <p>
              A value can carry more than one verified candidate (e.g. both an identity match and a
              real transform-based match) — reconciliation's per-record compare is the actual
              arbiter, so the pairing stage tolerates ambiguity rather than forcing a single winner.
            </p>
            <p className={styles.failureMode}>
              <strong>Failure mode:</strong> an LLM-proposed chain that references a non-allow-listed
              operation, uses invalid parameters, or simply doesn't produce the claimed value is
              rejected outright — never partially trusted, never silently corrected.
            </p>
            <SectionFooterNav id="stage-value-pairing" />

            <h3 id="stage-reconciliation">8. Reconciliation</h3>
            <StageKind llm={false} />
            <p>
              A full outer join on the business key classifies every record into one of three
              user-facing categories:
            </p>
            <ul>
              <li><strong>Match</strong> — compared fields agree within the configured match type.</li>
              <li>
                <strong>Quantity Mismatch</strong> — the business key exists on both sides, but a
                compared field disagrees.
              </li>
              <li>
                <strong>Mismatch</strong> — the business key exists on only one side. This is not a
                sum of two named sub-categories; it is every record whose key landed on only one side,
                regardless of which side. See <a href="#known-limits">Known Limits</a> for what this
                means in practice.
              </li>
            </ul>
            <p>
              Internally, the engine's <code>RecordClass</code> enum (
              <code>backend/recon_engine/models/results.py</code>) still distinguishes{" "}
              <code>missing_in_source</code> from <code>missing_in_target</code> at the record level —
              the collapse into a single user-facing <code>mismatch</code> bucket happens one layer up,
              in the reported summary.
            </p>
            <SectionFooterNav id="stage-reconciliation" />

            <h3 id="stage-results-lineage">9. Results + Lineage</h3>
            <StageKind llm={false} />
            <p>
              Every run, batch, and value pair carries a traceable identifier
              (<code>backend/recon_engine/ids.py</code>): <code>run_id</code> is a fresh, time-ordered
              id per run; <code>field_mapping_id</code> and <code>pair_id</code> are deterministic
              (the same logical mapping or pair always hashes to the same id, so it can be looked up
              rather than re-derived). Exports carry Run ID, Batch ID, Record ID, and Pair ID columns.
            </p>
            <Callout tone="scope" title="Known limitation">
              <p>
                <code>batch_id</code> and <code>record_id</code> are populated only in Auto-mode
                exports today — Manual-mode exports leave them blank.
              </p>
            </Callout>
            <SectionFooterNav id="stage-results-lineage" />
          </section>

          <section id="quality-gates">
            <h2>Quality Gates</h2>
            <p>Four independent mechanisms enforce the core principle in practice:</p>
            <ul>
              <li>
                <strong>Structural / allow-list validation (Gate 1)</strong> — a contract may only
                reference operations that exist in the fixed registry; an unknown operation name is
                rejected outright, never auto-created.
              </li>
              <li>
                <strong>Live-schema existence checks</strong> — Gate 1 also confirms every field an
                operation references actually exists in the real source/target schema fetched from
                the connectors or uploaded files, not an assumed or LLM-imagined column.
              </li>
              <li>
                <strong>Deterministic transform verification (Gate 2 + value-pairing's{" "}
                <code>verify_chain</code>)</strong> — Gate 2 replays a compiled contract against 50–100
                real sample records before approval; independently, every LLM-proposed value
                transform is re-executed against the real value it claims to transform (see stage 7).
                Both are the same idea applied at two different scopes: a claimed transform must
                actually reproduce the claimed result, character for character.
              </li>
              <li>
                <strong>Human approval</strong> — in Manual mode, an explicit <code>approved_by</code>{" "}
                is required before a contract becomes executable; no promotion happens automatically.
                Auto mode skips this specific checkpoint for the business key (see{" "}
                <a href="#known-limits">Known Limits</a>) but still runs Gate 1 and Gate 2 — auto-mode
                skips <em>confirmation</em>, never <em>validation</em>.
              </li>
            </ul>
            <SectionFooterNav id="quality-gates" />
          </section>

          <section id="transformation-contract">
            <h2>The Transformation Contract</h2>
            <p>
              A contract is data, never code. <code>ContractOperation</code> uses{" "}
              <code>extra=&quot;forbid&quot;</code> — there is deliberately no field anywhere in the
              schema for code, expressions, or scripts. An LLM can select and parameterize an
              operation from the registry; it cannot emit executable logic, because the schema has no
              slot to put it in even if it tried.
            </p>
            <JsonViewer
              className={styles.codeSample}
              language="json"
              filename="DraftContract (shape)"
              value={CONTRACT_SHAPE}
            />
            <p>
              Each operation is validated against its <code>OperationSpec</code> — required/optional
              parameters, and which parameters must themselves be real field names — before it can run:
            </p>
            <JsonViewer
              className={styles.codeSample}
              language="json"
              filename="backend/recon_engine/operations/registry.py (one entry)"
              value={REGISTRY_SAMPLE}
            />
            <p>
              The registry currently defines transform, filter, aggregate, and compare operations —
              things like <code>trim_string</code>, <code>remove_leading_zeros</code>,{" "}
              <code>exclude_value</code>, <code>group_by</code>, and <code>tolerance_match</code>. New
              operations are never auto-created by an LLM; a developer adds and tests one in{" "}
              <code>operations/ops.py</code> and registers its <code>OperationSpec</code> before an LLM
              can ever reference it by name.
            </p>
            <SectionFooterNav id="transformation-contract" />
          </section>

          <section id="reuse-learning">
            <h2>Reuse and Learning</h2>
            <p>
              Two separate libraries exist, and are kept separate deliberately — one storage comment
              notes this is <em>&quot;field mapping only; never value mapping&quot;</em>:
            </p>
            <ul>
              <li>
                <strong>Attribute (field) mapping library</strong> — keyed by the canonical, order-
                independent column-set of a source/target pair. Once a mapping has been approved on a
                contract, it is stored back into the library; the next run against the same column set
                resolves instantly via lookup instead of asking the LLM again.
              </li>
              <li>
                <strong>Value-pairing library</strong> — keyed by field mapping and the specific
                source/target value pair. A pairing that passed mandatory verification once is reused
                on every subsequent run without re-proposing or re-verifying it from scratch.
              </li>
            </ul>
            <p>
              Both stores dedupe on a canonical key (a UNIQUE constraint at the storage layer), so
              re-running the same reconciliation repeatedly narrows the amount of new LLM work needed
              over time rather than re-deriving everything from zero each time.
            </p>
            <SectionFooterNav id="reuse-learning" />
          </section>

          <section id="known-limits">
            <h2>Known Limits and What&apos;s Not Covered</h2>
            <Callout tone="scope" title="Auto mode's business-key self-approval">
              <p>
                Auto mode builds <code>business_key</code>/<code>compare_fields</code> from an LLM
                product/location identification plus deterministic date/quantity detection, then
                self-approves the contract (<code>approved_by=&quot;auto&quot;</code>) with no human
                review of that specific choice — unlike Manual mode, where a human always confirms the
                field mapping before a contract can be approved. Gate 1 and Gate 2 still run in both
                modes; only the human confirmation step differs.
              </p>
            </Callout>
            <Callout tone="scope" title="Reconciliation outcomes are not direction-split">
              <p>
                The three user-facing categories (Match, Quantity Mismatch, Mismatch) do not surface
                which side a one-sided record is missing from — a business key present only in the
                source and one present only in the target both report as &quot;Mismatch&quot;. The
                underlying <code>RecordClass</code> enum does retain the distinction internally.
              </p>
            </Callout>
            <Callout tone="scope" title="Coverage is data-dependent">
              <p>
                A value the pairing pipeline can't confidently match is often a genuine data-quality
                finding — a real discrepancy between systems — not a defect in the matching logic.
                Treat a low match rate as a lead to investigate, not automatically a bug report against
                the pipeline.
              </p>
            </Callout>
            <Callout tone="scope" title="Date-window mismatches">
              <p>
                When source and target extracts cover different date ranges, batching still runs
                correctly (a date present on only one side gets its own batch slot), but the resulting
                one-sided records are a data-completeness issue between the two systems' extracts, not
                a matching failure to be debugged in the pipeline itself.
              </p>
            </Callout>
            <Callout tone="medium" title="Planned">
              <p>
                A richer Gate 2 diagnostics engine — per-operation stage tracing, ranked failure-cause
                localization, and a shadow-data preview — is designed (
                <code>docs/gate2-diagnostics-and-contract-quality-design.md</code>) but not
                implemented; Gate 2 today reports pass/fail plus one message per check, without a
                per-stage breakdown of where a contract's sample replay collapsed.
              </p>
            </Callout>
            <SectionFooterNav id="known-limits" />
          </section>
        </article>
      </div>

      {showBackToTop && (
        <a href="#top" className={styles.backToTop} aria-label="Back to top">
          <FiArrowUp aria-hidden="true" /> Top
        </a>
      )}
    </div>
  );
}

export default DocsArchitecturePage;
