import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  FiPlay,
  FiArrowRight,
  FiArrowUpRight,
  FiLayers,
  FiBookOpen,
  FiBarChart2,
  FiArchive,
  FiDatabase,
} from "react-icons/fi";
import Counter from "../components/Counter";
import { useAuth } from "../auth/useAuth";
import "./homeContent.css";

const CAPABILITIES = [
  {
    key: "reconciliation",
    to: "/reconciliation",
    icon: FiLayers,
    accent: "var(--accent)",
    bg: "var(--accent-tint)",
    bd: "var(--accent-tint-2)",
    title: "Reconciliation Engine",
    description:
      "Guided wizard from connector selection through comparison type, transformation spec and run — with a shadow preview before anything commits.",
  },
  {
    key: "library",
    to: "/library",
    icon: FiBookOpen,
    accent: "var(--info)",
    bg: "var(--info-bg)",
    bd: "var(--info-bd)",
    title: "Library",
    description:
      "Reusable field mappings and value pairs, plus the fixed catalogue of transformations a recipe can apply.",
  },
  {
    key: "insights",
    to: "/insights",
    icon: FiBarChart2,
    accent: "var(--match)",
    bg: "var(--match-bg)",
    bd: "var(--match-bd)",
    title: "Insights",
    description:
      "Executive summary, hotspot heatmaps, root-cause boards and a readiness radar built from the run's own diagnostics.",
  },
  {
    key: "stored-runs",
    to: "/stored-runs",
    icon: FiArchive,
    accent: "var(--extra)",
    bg: "var(--extra-bg)",
    bd: "var(--extra-bd)",
    title: "Stored Runs",
    description:
      "Every reconciliation persisted with its inputs, contract and results — reopen, compare or export any historical run.",
  },
  {
    key: "data-sources",
    to: "/data-sources",
    icon: FiDatabase,
    accent: "var(--scope)",
    bg: "var(--scope-bg)",
    bd: "var(--scope-bd)",
    title: "Data Sources",
    description: "SAP S/4HANA, IBP, SQL and Excel connections in one place, with credentials encrypted at rest.",
  },
];

const STEPS = [
  {
    step: "STEP 01",
    highlight: true,
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
    tone: "home-support-card--dark",
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
  const { user } = useAuth();

  const metrics = useMemo(
    () => [
      { key: "total", label: "Total Reconciliations", value: 245 },
      { key: "accuracy", label: "Reconciliation Accuracy", display: "98.4%", accent: "var(--info)" },
      { key: "reports", label: "Total Reports Generated", value: 128 },
      { key: "issues", label: "Open Issues", value: 43, accent: "var(--qty)" },
    ],
    [],
  );

  const greeting = useMemo(() => {
    const h = new Date().getHours();
    return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
  }, []);
  const today = useMemo(
    () => new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" }),
    [],
  );
  const firstName = user?.full_name?.trim().split(/\s+/)[0];

  const heroPrimary = authed
    ? { label: "Start a reconciliation", onClick: () => navigate("/reconciliation") }
    : { label: "Sign in to workspace", onClick: () => navigate("/login") };

  const supportHref = (key) => {
    if (key === "contact") return "mailto:support@bristlecone.com";
    if (key === "architecture") return "/docs/architecture";
    return "#support";
  };

  // Only one h1 per page: the greeting owns it when present (authed), so the
  // hero headline steps down to h2; on the unauthenticated landing page (no
  // greeting) the hero headline is the page's h1.
  const HeroHeading = authed ? "h2" : "h1";

  return (
    <div className={`home-content${authed ? " home-content--authed" : ""}`}>
      {authed && (
        <section className="home-greeting">
          <div>
            <p className="home-greeting-date">{today}</p>
            <h1 className="home-greeting-title">
              {greeting}
              {firstName ? `, ${firstName}` : ""}
            </h1>
          </div>
          <div className="home-greeting-chip">
            <span className="home-greeting-dot" />
            <span>/reconciliation/run</span>
          </div>
        </section>
      )}

      <section className="home-hero">
        <div className="home-hero-card">
          <div className="home-hero-glow" aria-hidden="true" />
          <div className="home-hero-inner">
            <div className="home-chip-row">
              <span className="home-chip">SAP S/4HANA</span>
              <span className="home-chip-sep">↔</span>
              <span className="home-chip">IBP</span>
              <span className="home-chip-sep">↔</span>
              <span className="home-chip">BW</span>
              <span className="home-chip-sep">↔</span>
              <span className="home-chip">Datasphere</span>
              <span className="home-chip-sep">↔</span>
              <span className="home-chip home-chip--more">SQL · Excel · +more</span>
            </div>
            <HeroHeading className="home-h1">Reconcile SAP data with evidence, not spreadsheets.</HeroHeading>
            <p className="home-lede">
              One connected workspace for mapping, transformation, reconciliation and exception handling across your
              SAP landscape — with every match, gap and root cause traceable back to the source record.
            </p>
            <div className="home-hero-actions">
              <button type="button" className="btn-primary home-hero-primary" onClick={heroPrimary.onClick}>
                {heroPrimary.label}
                <FiArrowRight />
              </button>
              <a href="#demos" className="btn-secondary home-hero-secondary">
                <FiPlay />
                Watch the 3-min demo
              </a>
            </div>
            <p className="home-hero-footnote">
              Single sign-on · Encrypted connection credentials · Audit-ready run history
            </p>
          </div>
        </div>
      </section>

      <section className="home-metrics">
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3.5">
          {metrics.map((m) => (
            <div key={m.key} className="surface-elevated p-4">
              <div className="home-metric-label">{m.label}</div>
              <div className="mt-2.5">
                {m.value !== undefined ? (
                  <Counter value={m.value} fontSize={28} fontWeight={800} textColor={m.accent || "var(--ink)"} gap={0} />
                ) : (
                  <span className="home-metric-display" style={{ color: m.accent || "var(--ink)" }}>
                    {m.display}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section id="capabilities" className="home-section">
        <div className="home-section-head">
          <div>
            <h2 className="home-h2">One workspace, five connected surfaces</h2>
            <p className="home-section-sub">
              Every module in the platform reads the same contracts, the same mappings and the same run history.
            </p>
          </div>
        </div>
        <div className="home-capability-grid">
          {CAPABILITIES.map((c) => {
            const Icon = c.icon;
            const body = (
              <>
                <div className="home-capability-top">
                  <span
                    className="home-capability-icon"
                    style={{ background: c.bg, borderColor: c.bd, color: c.accent }}
                  >
                    <Icon />
                  </span>
                  {authed && <FiArrowUpRight className="home-capability-arrow" />}
                </div>
                <div className="home-capability-title">{c.title}</div>
                <p className="home-capability-desc">{c.description}</p>
              </>
            );
            return authed ? (
              <Link key={c.key} to={c.to} className="surface-elevated home-capability-card home-capability-card--link">
                {body}
              </Link>
            ) : (
              <div key={c.key} className="surface-elevated home-capability-card">
                {body}
              </div>
            );
          })}
        </div>
      </section>

      <section id="how" className="home-section">
        <div className="home-section-head">
          <h2 className="home-h2">How a reconciliation runs</h2>
        </div>
        <div className="home-step-grid">
          {STEPS.map((s) => (
            <div key={s.step} className="home-step-card">
              <div className={`home-step-track${s.highlight ? " home-step-track--active" : ""}`}>
                {s.highlight && <span className="home-step-track-fill" />}
              </div>
              <div className={`home-step-eyebrow${s.highlight ? " home-step-eyebrow--active" : ""}`}>{s.step}</div>
              <div className="home-step-title">{s.title}</div>
              <p className="home-step-desc">{s.description}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="demos" className="home-section">
        <div className="home-section-head">
          <div>
            <h2 className="home-h2">Demo library</h2>
            <p className="home-section-sub">Short walkthroughs recorded from the live product.</p>
          </div>
          <a href="#support" className="home-demos-cta">
            Request a guided session →
          </a>
        </div>
        <div className="home-demo-grid">
          {DEMOS.map((d) => (
            <div key={d.key} className="surface-elevated home-demo-card">
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
        <div className="home-section-head">
          <h2 className="home-h2">Support &amp; enablement</h2>
        </div>
        <div className="home-support-grid">
          {SUPPORT_CARDS.map((s) => {
            const href = supportHref(s.key);
            const isInternalRoute = href.startsWith("/");
            return (
              <div key={s.key} className={`home-support-card ${s.tone}`}>
                <div className="home-support-title">{s.title}</div>
                <p className="home-support-desc">{s.description}</p>
                {isInternalRoute ? (
                  <Link to={href} className="home-support-link">
                    {s.label}
                  </Link>
                ) : (
                  <a href={href} className="home-support-link">
                    {s.label}
                  </a>
                )}
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}

export default HomeContent;
