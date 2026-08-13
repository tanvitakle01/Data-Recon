// Right-side slide-out panel for the Auto-mode error-resolver bot — opened
// automatically when the Auto-run pauses on a RECOVERABLE resolution failure
// (entity/field/join-key not resolved; see backend/.../auto_pipeline/
// interrupts.py), dismissible/re-openable without losing the paused run.
//
// Purely presentational: it renders whatever `interrupt` payload the backend
// sent (ranked chips + the full live-options list + a plain-language
// question) and calls `onSubmit(value)` for either a chip tap or typed text
// — identically, since the backend validates both the same way. It knows
// nothing about polling or the auto-run lifecycle, so mounting it on another
// step later is wiring (a different `interrupt`/`onSubmit` source), not a
// rewrite.
import { useEffect, useState } from "react";
import { X, Sparkles } from "lucide-react";
import { Alert, Button } from "@bristlecone/canopy";

const RESOLVER_LABELS = {
  entity: "Entity",
  field: "Field",
  join_key: "Join key",
};

function ResolverPanel({ open, interrupt, busy, error, onSubmit, onClose }) {
  const [freeText, setFreeText] = useState("");
  const [showAll, setShowAll] = useState(false);

  // A fresh question (even a re-ask on the same checkpoint) starts the free
  // text and "show all" state clean — the previous attempt is done with.
  // Adjusted during render (not an effect) per React's guidance for resetting
  // state when a derived key changes, so this never cascades an extra render.
  const interruptKey = interrupt ? `${interrupt.message}|${interrupt.attempted}` : null;
  const [prevInterruptKey, setPrevInterruptKey] = useState(interruptKey);
  if (interruptKey !== prevInterruptKey) {
    setPrevInterruptKey(interruptKey);
    setFreeText("");
    setShowAll(false);
  }

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  const options = interrupt?.options ?? [];
  const allOptions = interrupt?.all_options ?? [];
  const extraOptions = allOptions.filter((o) => !options.includes(o));

  const submitFreeText = () => {
    const value = freeText.trim();
    if (!value || busy) return;
    onSubmit(value);
  };

  return (
    <>
      <div
        className={`ct-drawer-backdrop${open ? " is-open" : ""}`}
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        className={`ct-drawer ct-resolver-drawer${open ? " is-open" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label="Resolve to continue"
        aria-hidden={!open}
      >
        <div className="ct-drawer__head">
          <Sparkles size={16} aria-hidden />
          <h3 className="ct-drawer__title">Resolve to continue</h3>
          <button
            type="button"
            className="ct-drawer__close"
            onClick={onClose}
            aria-label="Close resolver panel"
          >
            <X size={18} />
          </button>
        </div>
        <div className="ct-drawer__body">
          {!interrupt ? (
            <p className="wizard-field__help" style={{ marginTop: 0 }}>
              Nothing needs your input right now.
            </p>
          ) : (
            <div className="ct-resolver">
              <section className="ct-card ct-card--tint-yellow">
                <div className="ct-card__body">
                  {interrupt.resolver && (
                    <span className="ct-resolver__kind">
                      {RESOLVER_LABELS[interrupt.resolver] ?? interrupt.resolver}
                      {interrupt.kind ? ` · ${interrupt.kind.toUpperCase()}` : ""}
                    </span>
                  )}
                  <p className="ct-resolver__message">{interrupt.message}</p>
                </div>
              </section>

              {options.length > 0 && (
                <section className="ct-card">
                  <div className="ct-card__head">
                    <h4 className="ct-card__title">Closest matches</h4>
                  </div>
                  <div className="ct-card__body">
                    <div className="ct-resolver__chips">
                      {options.map((opt) => (
                        <button
                          key={opt}
                          type="button"
                          className="ct-resolver__chip"
                          disabled={busy}
                          onClick={() => onSubmit(opt)}
                        >
                          {opt}
                        </button>
                      ))}
                    </div>
                    {extraOptions.length > 0 && (
                      <button
                        type="button"
                        className="wizard-link"
                        style={{ marginTop: 8 }}
                        onClick={() => setShowAll((v) => !v)}
                      >
                        {showAll
                          ? "Hide other options"
                          : `Show all options (${allOptions.length} total)`}
                      </button>
                    )}
                    {showAll && extraOptions.length > 0 && (
                      <div className="ct-resolver__chips" style={{ marginTop: 8 }}>
                        {extraOptions.map((opt) => (
                          <button
                            key={opt}
                            type="button"
                            className="ct-resolver__chip ct-resolver__chip--muted"
                            disabled={busy}
                            onClick={() => onSubmit(opt)}
                          >
                            {opt}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </section>
              )}

              <section className="ct-card">
                <div className="ct-card__head">
                  <h4 className="ct-card__title">Or type the correct value</h4>
                </div>
                <div className="ct-card__body">
                  <div className="ct-resolver__freetext">
                    <input
                      type="text"
                      className="wizard-instructions__textarea ct-resolver__input"
                      placeholder={interrupt.attempted || "Type the correct value…"}
                      value={freeText}
                      disabled={busy}
                      onChange={(e) => setFreeText(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") submitFreeText();
                      }}
                    />
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={submitFreeText}
                      loading={busy}
                      disabled={busy || !freeText.trim()}
                    >
                      Resolve
                    </Button>
                  </div>
                </div>
              </section>

              {error && <Alert variant="error">{error}</Alert>}
            </div>
          )}
        </div>
      </aside>
    </>
  );
}

export default ResolverPanel;
