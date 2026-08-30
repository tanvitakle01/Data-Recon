import styles from "./pipelineDiagram.module.css";

// Schematic (not to scale) of the pipeline described in the surrounding text.
// Node border style carries the deterministic/LLM-assisted distinction so it
// survives grayscale printing and color-blind viewing, not just color; the
// legend restates it in text. See the "Pipeline Stages" section for the
// file-level evidence behind each node.
const W = 640;
const GAP = 30;
const H1 = 44;
const WIDE = 560;
const NARROW = 500;

function Node({ x, y, w, h, label, sub, kind, id }) {
  const dashed = kind === "llm";
  const human = kind === "human";
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={10}
        style={{
          fill: "var(--surface)",
          stroke: "var(--border-strong)",
          strokeWidth: 1.5,
          strokeDasharray: dashed ? "6 4" : "none",
        }}
      />
      {human && <rect x={x} y={y} width={4} height={h} rx={2} style={{ fill: "var(--accent)" }} />}
      <text
        x={x + w / 2}
        y={y + (sub ? h / 2 - 6 : h / 2 + 4)}
        textAnchor="middle"
        style={{ fill: "var(--ink)", fontSize: 13, fontWeight: 650, fontFamily: "var(--sans)" }}
      >
        {label}
      </text>
      {sub && (
        <text
          x={x + w / 2}
          y={y + h / 2 + 14}
          textAnchor="middle"
          style={{ fill: "var(--muted)", fontSize: 10.5, fontFamily: "var(--sans)" }}
        >
          {sub}
        </text>
      )}
      <title>{id ? `${id}: ${label}` : label}</title>
    </g>
  );
}

function Arrow({ x, y1, y2 }) {
  return (
    <g>
      <line x1={x} y1={y1} x2={x} y2={y2 - 8} style={{ stroke: "var(--muted-2)", strokeWidth: 1.5 }} />
      <polygon points={`${x - 5},${y2 - 8} ${x + 5},${y2 - 8} ${x},${y2}`} style={{ fill: "var(--muted-2)" }} />
    </g>
  );
}

export default function PipelineDiagram() {
  const cx = W / 2;

  // Sequential layout — each y is derived from the previous node's bottom
  // edge, so the coordinate math and the rendered nodes can never drift out
  // of sync with each other.
  let y = 24;
  const yIngest = y;
  y += H1 + GAP;
  const yAttr = y;
  y += H1 + GAP;
  const yKey = y;
  y += H1 + GAP;
  const yDate = y;
  y += H1 + GAP;

  const gatesTop = y;
  const gateH = 56;
  const gateW = 172;
  const gateGap = 22;
  const gatesLeft = cx - (gateW * 3 + gateGap * 2) / 2;
  const gates = [
    { x: gatesLeft, label: "Gate 1", sub: "Structural + live-schema check", kind: "det" },
    { x: gatesLeft + gateW + gateGap, label: "Gate 2", sub: "Sample replay (50–100 rows)", kind: "det" },
    { x: gatesLeft + (gateW + gateGap) * 2, label: "Human Approval", sub: "Manual mode only — see Known Limits", kind: "human" },
  ];
  y += gateH + GAP;

  const yBatch = y;
  y += H1 + GAP;

  const loopTop = y;
  const yDistinct = y;
  y += H1 + GAP;
  const yPairLookup = y;
  y += 40 + GAP;
  const yPairLLM = y;
  y += 40 + GAP;
  const yVerify = y;
  y += 44 + GAP;
  const loopBottom = y - GAP;

  const yRecon = y;
  y += H1 + GAP;
  const yResults = y;
  y += H1;

  const totalHeight = y + 20;

  return (
    <figure className={styles.wrap}>
      <div className={styles.scroller}>
        <svg
          viewBox={`0 0 ${W} ${totalHeight}`}
          role="img"
          aria-labelledby="pipeline-diagram-title pipeline-diagram-desc"
          className={styles.svg}
        >
          <title id="pipeline-diagram-title">Reconciliation pipeline flow</title>
          <desc id="pipeline-diagram-desc">
            Nine sequential stages: ingestion, attribute mapping, key and compare classification,
            date-field identification, date-aligned batching, distinct value extraction, value
            pairing, reconciliation, and results with lineage. Stages 1, 4, 5, 8 and 9 are fully
            deterministic. Stages 2 and 3 are LLM-assisted proposals that a human confirms.
            Between stage 4 and stage 5, a compiled contract passes through Gate 1 (structural and
            live-schema validation), Gate 2 (sample replay against real data), and — in Manual
            mode only — an explicit human approval step; Auto mode self-approves this step, a
            known gap described in the Known Limits section. Stages 6 and 7 repeat once per date
            batch: distinct value extraction is deterministic, and value pairing tries a
            deterministic library lookup and identity pre-pass first, falling back to an
            LLM-proposed transform only for values neither resolves — every proposal, regardless
            of source, is then mechanically re-executed and verified before it can reach
            reconciliation.
          </desc>

          <Node x={cx - WIDE / 2} y={yIngest} w={WIDE} h={H1} kind="det" id="ingestion"
            label="1 · Ingestion" sub="Mapping sheet / connector / Excel · entity + field resolution" />
          <Arrow x={cx} y1={yIngest + H1} y2={yAttr} />

          <Node x={cx - WIDE / 2} y={yAttr} w={WIDE} h={H1} kind="llm" id="attribute-mapping"
            label="2 · Attribute Mapping" sub="LLM proposes column ↔ column pairs · human-confirmable table" />
          <Arrow x={cx} y1={yAttr + H1} y2={yKey} />

          <Node x={cx - WIDE / 2} y={yKey} w={WIDE} h={H1} kind="llm" id="key-compare"
            label="3 · Key / Compare Classification" sub="LLM proposes business_key / compare_fields" />
          <Arrow x={cx} y1={yKey + H1} y2={yDate} />

          <Node x={cx - WIDE / 2} y={yDate} w={WIDE} h={H1} kind="det" id="date-detection"
            label="4 · Date-Field Identification" sub="Deterministic regex + pandas parse, never an LLM guess" />
          <Arrow x={cx} y1={yDate + H1} y2={gatesTop} />

          {gates.map((g) => (
            <Node key={g.label} x={g.x} y={gatesTop} w={gateW} h={gateH} label={g.label} sub={g.sub} kind={g.kind} />
          ))}
          <Arrow x={cx} y1={gatesTop + gateH} y2={yBatch} />

          <Node x={cx - NARROW / 2} y={yBatch} w={NARROW} h={H1} kind="det" id="batching"
            label="5 · Date-Aligned Batching" sub="A date is never split across batches" />

          <rect
            x={cx - 500 / 2 - 16}
            y={loopTop - 16}
            width={500 + 32}
            height={loopBottom - loopTop + 32}
            rx={14}
            style={{ fill: "none", stroke: "var(--accent)", strokeDasharray: "3 5", strokeWidth: 1.5 }}
          />
          <text
            x={cx - 500 / 2 - 16 + 12}
            y={loopTop - 22}
            style={{ fill: "var(--accent)", fontSize: 10.5, fontWeight: 700, fontFamily: "var(--sans)", letterSpacing: "0.03em" }}
          >
            REPEATS ONCE PER BATCH
          </text>

          <Arrow x={cx} y1={yBatch + H1} y2={yDistinct} />
          <Node x={cx - 480 / 2} y={yDistinct} w={480} h={H1} kind="det" id="distinct-values"
            label="6 · Distinct Value Extraction" sub="Per batch — blank/null dropped" />
          <Arrow x={cx} y1={yDistinct + H1} y2={yPairLookup} />

          <Node x={cx - 460 / 2} y={yPairLookup} w={460} h={40} kind="det"
            label="Library lookup → Identity pre-pass" sub="Both deterministic — reused/exact values resolve immediately" />
          <Arrow x={cx} y1={yPairLookup + 40} y2={yPairLLM} />

          <Node x={cx - 460 / 2} y={yPairLLM} w={460} h={40} kind="llm"
            label="LLM residual proposal" sub="Only for values neither step above resolved" />
          <Arrow x={cx} y1={yPairLLM + 40} y2={yVerify} />

          <Node x={cx - 460 / 2} y={yVerify} w={460} h={44} kind="det" id="value-pairing"
            label="7 · Mandatory Deterministic Verification" sub="Re-executes every proposed op chain — reject on any mismatch" />

          <Arrow x={cx} y1={loopBottom + 16} y2={yRecon} />
          <Node x={cx - NARROW / 2} y={yRecon} w={NARROW} h={H1} kind="det" id="reconciliation"
            label="8 · Reconciliation" sub="Full outer join → Match / Quantity Mismatch / Mismatch" />
          <Arrow x={cx} y1={yRecon + H1} y2={yResults} />

          <Node x={cx - NARROW / 2} y={yResults} w={NARROW} h={H1} kind="det" id="results-lineage"
            label="9 · Results + Lineage" sub="run_id / batch_id / pair_id traceability" />
        </svg>
      </div>

      <figcaption className={styles.legend} aria-hidden="true">
        <span className={styles.legendItem}>
          <span className={`${styles.swatch} ${styles.swatchDet}`} /> Deterministic
        </span>
        <span className={styles.legendItem}>
          <span className={`${styles.swatch} ${styles.swatchLlm}`} /> LLM-assisted (always re-verified or human-confirmed)
        </span>
        <span className={styles.legendItem}>
          <span className={`${styles.swatch} ${styles.swatchHuman}`} /> Human checkpoint
        </span>
      </figcaption>
    </figure>
  );
}
