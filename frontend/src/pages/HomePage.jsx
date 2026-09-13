import { useNavigate } from "react-router-dom";
import { FiArrowRight } from "react-icons/fi";
import "./homeContent.css";

const STEPS = [
  {
    step: "STEP 01",
    highlight: true,
    title: "Choose dataset type",
    description: "Tell the engine what kind of source and target you're comparing.",
  },
  {
    step: "STEP 02",
    title: "Upload source & target",
    description: "Upload the source and target workbooks for this session.",
  },
  {
    step: "STEP 03",
    title: "Review mapping",
    description: "Confirm proposed field matches, or use a mapping sheet to drive the match automatically.",
  },
  {
    step: "STEP 04",
    title: "Run & resolve",
    description: "Matches, gaps and quantity breaks land in results, ready to investigate.",
  },
];

/** Rendered inside AppLayout at "/home". All state for a reconciliation run
 * lives only for the current browser session — nothing here is backed by
 * stored history. */
function HomePage() {
  const navigate = useNavigate();

  return (
    <div className="home-content home-content--authed">
      <section className="home-hero">
        <div className="home-hero-card">
          <div className="home-hero-glow" aria-hidden="true" />
          <div className="home-hero-inner">
            <div className="home-chip-row">
              <span className="home-chip">Excel</span>
              <span className="home-chip-sep">↔</span>
              <span className="home-chip">Excel</span>
            </div>
            <h1 className="home-h1">Reconcile data with evidence, not spreadsheets.</h1>
            <p className="home-lede">
              Upload a source and target workbook and walk through mapping, transformation and reconciliation in one
              guided session — with a preview before anything is compared.
            </p>
            <div className="home-hero-actions">
              <button
                type="button"
                className="btn-primary home-hero-primary"
                onClick={() => navigate("/reconciliation")}
              >
                Start a reconciliation
                <FiArrowRight />
              </button>
            </div>
            <p className="home-hero-footnote">File upload only · Nothing is stored after your session ends</p>
          </div>
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
    </div>
  );
}

export default HomePage;
