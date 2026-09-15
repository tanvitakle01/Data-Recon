import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { FiArrowRight, FiChevronLeft, FiChevronRight, FiImage } from "react-icons/fi";
import "./homeContent.css";

// What the AI is allowed to see, never sees, and what actually executes. This
// is the app's strongest guarantee, so it's stated as content rather than as a
// screenshot — it needs no asset and can't go stale against the UI.
const GUARDRAIL_ROWS = [
  { key: "sees", label: "Sees", text: "Mapping sheet text · column headers" },
  { key: "never", label: "Never sees", text: "Any row of your source or target data" },
  { key: "executes", label: "Executes", text: "Deterministic engine, allow-listed operations" },
];

// Slides 2 and 3 illustrate a real screen. Drop the PNGs into frontend/public/
// under these names and they appear automatically; until then each renders a
// labelled empty frame rather than a broken image.
const TOUR = [
  {
    key: "guardrail",
    eyebrow: "By default",
    title: "No row-level data ever reaches an AI model.",
    body:
      "The AI reads only your mapping sheet's text and the column headers of the files you upload. Every transformation and every comparison runs through a deterministic executor.",
  },
  {
    key: "mapping",
    eyebrow: "Before it runs",
    title: "Every field pair, laid out for you.",
    body:
      "The Mapping step lists each target field alongside its source table and field, its role as a key or compared value, and the match confidence — reconciled automatically, and editable anytime you want to adjust it.",
    image: "/tour-mapping.png",
    alt: "The Mapping step's field mapping table",
    placeholder: "Screenshot of the Mapping step",
  },
  {
    key: "results",
    eyebrow: "After the run",
    title: "Matches, quantity breaks and gaps, side by side.",
    body:
      "Results break the run into matches, quantity mismatches and records missing on either side, filterable by outcome and downloadable as a comparison sheet.",
    image: "/tour-results.png",
    alt: "The downloaded comparison sheet's run summary",
    placeholder: "Screenshot of the comparison sheet",
  },
];

const HOW_IT_WORKS = [
  {
    step: "STEP 01",
    title: "Upload your mapping sheet",
    description:
      "The sheet defines the interfaces, the field pairs and the join — so nothing has to be hand-built per interface.",
  },
  {
    step: "STEP 02",
    title: "Upload source and target data",
    description:
      "Your S/4HANA extract and your IBP extract. Each side is previewed before anything is compared.",
  },
  {
    step: "STEP 03",
    title: "Get reconciled results",
    description:
      "Matches, quantity breaks and gaps, with the transformation chain shown for review before it executes.",
  },
];

/** A tour image that degrades to a labelled frame when the PNG isn't there yet,
 * so an un-dropped screenshot never renders as a broken image. */
function TourImage({ src, alt, placeholder }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <div className="home-tour-media__empty">
        <FiImage aria-hidden />
        <span>{placeholder}</span>
      </div>
    );
  }
  return <img className="home-tour-media__img" src={src} alt={alt} onError={() => setFailed(true)} />;
}

/** Rendered inside AppLayout at "/home". All state for a reconciliation run
 * lives only for the current browser session — nothing here is backed by
 * stored history. */
function HomePage() {
  const navigate = useNavigate();
  const [slideIdx, setSlideIdx] = useState(0);
  const slide = TOUR[slideIdx];

  const move = (delta) => setSlideIdx((i) => (i + delta + TOUR.length) % TOUR.length);

  return (
    <div className="home-content">
      {/* ══ Hero ══ */}
      <section className="home-hero">
        <div className="home-hero-card">
          <div className="home-hero-grid-bg" aria-hidden="true" />
          <div className="home-hero-grid">
            <div className="home-hero-copy">
              <div className="home-eyebrow-row">
                <span className="home-eyebrow-dash" aria-hidden="true" />
                <p className="home-eyebrow">source→ target</p>
              </div>
              <h1 className="home-h1">
                Data Reconciliation Tool
              </h1>
              <p className="home-lede">
                Upload a mapping sheet describing how your source and target line up
                <br/>
                and the engine handles the rest — driven entirely by 
                <br/>
                your mapping sheet, with no per-system rules to hand-code
              </p>
              <div className="home-hero-actions">
                <button
                  type="button"
                  className="home-btn home-btn--primary"
                  onClick={() => navigate("/reconciliation")}
                >
                  Start a reconciliation
                  <FiArrowRight aria-hidden />
                </button>
              </div>
              <div className="home-meta-row">
                <span>Mapping-sheet driven</span>
                <span className="home-meta-sep" aria-hidden="true" />
                <span>Deterministic executor</span>
                <span className="home-meta-sep" aria-hidden="true" />
                <span>Stateless session</span>
              </div>
            </div>

            {/* ══ Product tour ══ */}
            <section className="home-tour" aria-label="Product tour">
              <span className="home-tour__topbar" aria-hidden="true" />
              <header className="home-tour__head">
                <span className="home-tour__dot" aria-hidden="true" />
                <p className="home-tour__eyebrow">{slide.eyebrow}</p>
                <span className="home-tour__counter">
                  {String(slideIdx + 1).padStart(2, "0")} / {String(TOUR.length).padStart(2, "0")}
                </span>
              </header>

              <div className="home-tour-media">
                {slide.key === "guardrail" ? (
                  <div className="home-guardrail">
                    <div className="home-guardrail__group">
                      {GUARDRAIL_ROWS.map((row) => (
                        <div key={row.key} className="home-guardrail__row">
                          <span
                            className={`home-guardrail__label home-guardrail__label--${row.key}`}
                          >
                            {row.label}
                          </span>
                          <span className="home-guardrail__text">{row.text}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <TourImage src={slide.image} alt={slide.alt} placeholder={slide.placeholder} />
                )}
              </div>

              <h2 className="home-tour__title">{slide.title}</h2>
              <p className="home-tour__body">{slide.body}</p>

              <footer className="home-tour__foot">
                <div className="home-tour__dots" role="tablist" aria-label="Tour slides">
                  {TOUR.map((t, i) => (
                    <button
                      key={t.key}
                      type="button"
                      role="tab"
                      aria-label={t.eyebrow}
                      aria-selected={i === slideIdx}
                      className={`home-tour__pip ${i === slideIdx ? "is-active" : ""}`}
                      onClick={() => setSlideIdx(i)}
                    />
                  ))}
                </div>
                <button
                  type="button"
                  className="home-tour__nav"
                  aria-label="Previous slide"
                  onClick={() => move(-1)}
                >
                  <FiChevronLeft aria-hidden />
                </button>
                <button
                  type="button"
                  className="home-tour__nav home-tour__nav--next"
                  aria-label="Next slide"
                  onClick={() => move(1)}
                >
                  <FiChevronRight aria-hidden />
                </button>
              </footer>
            </section>
          </div>
        </div>
      </section>

      {/* ══ How it works ══ */}
      <section id="how" className="home-section">
        <div className="home-section-head">
          <div>
            <h2 className="home-h2">How it works</h2>
          </div>
        </div>
        <div className="home-step-grid">
          {HOW_IT_WORKS.map((s, i) => (
            <div key={s.step} className={`home-step-card ${i === 0 ? "is-first" : ""}`}>
              <span className="home-step-card__rule" aria-hidden="true" />
              <div className="home-step-card__head">
                <span className="home-step-card__eyebrow">{s.step}</span>
                <span className="home-step-card__ghost" aria-hidden="true">
                  {String(i + 1).padStart(2, "0")}
                </span>
              </div>
              <div className="home-step-card__title">{s.title}</div>
              <p className="home-step-card__desc">{s.description}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ══ Plan / deploy / control ══ */}
      <section className="home-section home-section--tail">
        <div className="home-info-grid">
          <div className="home-info-card home-info-card--blue">
            <span className="home-info-card__rule" aria-hidden="true" />
            <p className="home-info-card__eyebrow">AI engine</p>
            <div className="home-info-card__title">Built in, ready to run</div>
            <p className="home-info-card__desc">
              Mapping detection and transformation drafting run on the model the app is configured
              with. No keys to obtain, enter, or manage.
            </p>
          </div>
          <div className="home-info-card home-info-card--yellow">
            <span className="home-info-card__rule" aria-hidden="true" />
            <p className="home-info-card__eyebrow">Deploy</p>
            <div className="home-info-card__title">Nothing to configure, nothing to leak</div>
            <p className="home-info-card__desc">
              No sign-in and no database. The engine runs statelessly per session — your data lives
              only as long as the tab is open.
            </p>
          </div>
          <div className="home-info-card">
            <span className="home-info-card__rule" aria-hidden="true" />
            <p className="home-info-card__eyebrow">Control</p>
            <div className="home-info-card__title">Auto-detected, editable anytime</div>
            <p className="home-info-card__desc">
              Rules are detected and applied automatically — no setup required. Want to change something? Edit the rules and re-run whenever you like.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}

export default HomePage;
