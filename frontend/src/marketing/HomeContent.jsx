import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { FiPlay } from "react-icons/fi";
import Counter from "../components/Counter";
import "./homeContent.css";

const CAPABILITIES = [
  {
    key: "reconciliation",
    to: "/reconciliation",
    accent: "var(--accent)",
    title: "Reconciliation Engine",
    description:
      "Guided wizard from connector selection through comparison type, transformation spec and run — with a shadow preview before anything commits.",
  },
  {
    key: "library",
    to: "/library",
    accent: "var(--info)",
    title: "Mapping Library",
    description:
      "Reusable field mappings with confidence tiers, review drawers and side-by-side before/after on every proposed change.",
  },
  {
    key: "insights",
    to: "/insights",
    accent: "var(--match)",
    title: "Insights",
    description:
      "Executive summary, hotspot heatmaps, root-cause boards and a readiness radar built from the run's own diagnostics.",
  },
  {
    key: "stored-runs",
    to: "/stored-runs",
    accent: "var(--extra)",
    title: "Stored Runs",
    description:
      "Every reconciliation persisted with its inputs, contract and results — reopen, compare or export any historical run.",
  },
  {
    key: "data-sources",
    to: "/data-sources",
    accent: "var(--scope)",
    title: "Data Sources",
    description: "SAP S/4HANA, IBP, SQL and Excel connections in one place, with credentials encrypted at rest.",
  },
];

const STEPS = [
  {
    step: "STEP 01",
    title: "Connect sources",
    description: "Pick the two datasets — S/4HANA against IBP, SQL or an uploaded workbook.",
  },
  {
    step: "STEP 02",
    title: "Review mapping",
    description: "Confirm proposed field matches by confidence tier, or edit them in the review drawer.",
  },
  {
    step: "STEP 03",
    title: "Preview transforms",
    description: "See the transformation spec applied to sample rows before the run touches anything.",
  },
  {
    step: "STEP 04",
    title: "Run & resolve",
    description: "Matches, gaps and quantity breaks land in results, ready to investigate.",
  },
];

const DEMOS = [
  {
    key: "getting-started",
    title: "Getting started",
    duration: "03:12",
    description: "Sign in, connect S/4HANA and run your first reconciliation end to end.",
  },
  {
    key: "mapping-review",
    title: "Mapping review & confidence tiers",
    duration: "05:40",
    description: "How proposed field matches are scored, edited and approved before a run.",
  },
];

const SUPPORT_CARDS = [
  {
    key: "setup",
    tone: "home-support-card--blue",
    title: "Setup guide",
    description: "Supabase auth, encrypted connection secrets and environment provisioning, step by step.",
    label: "Read SETUP.md →",
  },
  {
    key: "architecture",
    tone: "home-support-card--yellow",
    title: "Architecture notes",
    description: "Transformation spec design, contract quality gates and the LLM contract-only rule.",
    label: "Browse the docs →",
  },
  {
    key: "contact",
    tone: "home-support-card--plain",
    title: "Talk to the team",
    description: "Reach out or book a walkthrough with the reconciliation platform team.",
    label: "Contact support →",
  },
];

/**
 * Shared between the public landing page (`authed=false`) and the
 * authenticated "/home" sidebar destination (`authed=true`). The header,
 * footer and full-viewport shell live in the callers — this only renders the
 * sections that are identical in both places.
 */
function HomeContent({ authed = false }) {
  const navigate = useNavigate();

  const metrics = useMemo(
    () => [
      { key: "total", label: "Total Reconciliations", value: 245, accent: "var(--info)" },
      { key: "accuracy", label: "Reconciliation Accuracy", display: "98.4%", accent: "var(--match)" },
      { key: "reports", label: "Total Reports Generated", value: 128, accent: "var(--accent)" },
      { key: "issues", label: "Open Issues", value: 43, accent: "var(--qty)" },
    ],
    [],
  );

  const heroPrimary = authed
    ? { label: "Start a reconciliation", onClick: () => navigate("/reconciliation") }
    : { label: "Sign in to workspace", onClick: () => navigate("/login") };

  const supportHref = (key) => {
    if (key !== "contact") return "#support";
    return "mailto:support@bristlecone.com";
  };

  return (
    <div className={`home-content${authed ? " home-content--authed" : ""}`}>
      <section className="home-hero">
        <div>
          <p className="home-eyebrow">SAP S/4HANA &nbsp;↔&nbsp; IBP &nbsp;↔&nbsp; SQL &nbsp;↔&nbsp; Excel</p>
          <h1 className="home-h1">Reconcile SAP data with evidence, not spreadsheets.</h1>
          <p className="home-lede">
            One connected workspace for mapping, transformation, reconciliation and exception handling across your
            SAP landscape — with every match, gap and root cause traceable back to the source record.
          </p>
          <div className="flex items-center gap-3 mt-7">
            <button type="button" className="btn-primary" onClick={heroPrimary.onClick}>
              {heroPrimary.label}
            </button>
            <a href="#demos" className="btn-secondary">
              Watch the 3-min demo
            </a>
          </div>
          <p className="home-hero-footnote">Single sign-on · Encrypted connection credentials · Audit-ready run history</p>
        </div>
        <div className="home-hero-frame">
          <div className="home-hero-chrome">
            <span className="home-hero-dot" />
            <span className="home-hero-dot" />
            <span className="home-hero-dot" />
            <span className="home-hero-path">/reconciliation/run</span>
          </div>
          <div className="home-hero-shot" aria-hidden="true" />
        </div>
      </section>

      <section className="home-metrics">
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3.5">
          {metrics.map((m) => (
            <div
              key={m.key}
              className="surface-elevated accent-bar p-4"
              style={{ borderLeftColor: m.accent }}
            >
              <div className="home-metric-label">{m.label}</div>
              <div className="mt-2.5">
                {m.value !== undefined ? (
                  <Counter value={m.value} fontSize={28} fontWeight={800} textColor="var(--ink)" gap={0} />
                ) : (
                  <span className="home-metric-display">{m.display}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section id="capabilities" className="home-section">
        <h2 className="home-h2">One workspace, five connected surfaces</h2>
        <p className="home-section-sub">
          Every module in the platform reads the same contracts, the same mappings and the same run history.
        </p>
        <div className="home-capability-grid">
          {CAPABILITIES.map((c) =>
            authed ? (
              <Link
                key={c.key}
                to={c.to}
                className="surface-elevated accent-bar home-capability-card home-capability-card--link"
                style={{ borderLeftColor: c.accent }}
              >
                <div className="home-capability-title">{c.title}</div>
                <p className="home-capability-desc">{c.description}</p>
              </Link>
            ) : (
              <div
                key={c.key}
                className="surface-elevated accent-bar home-capability-card"
                style={{ borderLeftColor: c.accent }}
              >
                <div className="home-capability-title">{c.title}</div>
                <p className="home-capability-desc">{c.description}</p>
              </div>
            ),
          )}
        </div>
      </section>

      <section id="how" className="home-section">
        <h2 className="home-h2 mb-7">How a reconciliation runs</h2>
        <div className="home-step-grid">
          {STEPS.map((s) => (
            <div key={s.step} className="surface-elevated home-step-card">
              <div className="home-step-eyebrow">{s.step}</div>
              <div className="home-step-title">{s.title}</div>
              <p className="home-step-desc">{s.description}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="demos" className="home-demos">
        <div className="home-demos-head">
          <div>
            <h2 className="home-h2 home-h2--light">Demo library</h2>
            <p className="home-section-sub home-section-sub--light">
              Short walkthroughs recorded from the live product.
            </p>
          </div>
          <a href="#support" className="home-demos-cta">
            Request a guided session →
          </a>
        </div>
        <div className="home-demo-grid">
          {DEMOS.map((d) => (
            <div key={d.key} className="home-demo-card">
              <div className="home-demo-poster">
                <span className="home-demo-play">
                  <FiPlay />
                </span>
                <span className="home-demo-duration">{d.duration}</span>
              </div>
              <div className="home-demo-body">
                <div className="home-demo-title">{d.title}</div>
                <p className="home-demo-desc">{d.description}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section id="support" className="home-section">
        <h2 className="home-h2 mb-7">Support & enablement</h2>
        <div className="home-support-grid">
          {SUPPORT_CARDS.map((s) => (
            <div key={s.key} className={`home-support-card ${s.tone}`}>
              <div className="home-support-title">{s.title}</div>
              <p className="home-support-desc">{s.description}</p>
              <a href={supportHref(s.key)} className="home-support-link">
                {s.label}
              </a>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

export default HomeContent;
