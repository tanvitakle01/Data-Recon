import { useCallback } from "react";

function HeroActions() {
  // UI-only buttons; wire to existing upload flow in a later pass.
  const onPrimary = useCallback(() => {
    // no-op (keeps enterprise feel; avoids broken navigation)
    window.dispatchEvent(new Event("recon-hero-primary"));
  }, []);

  const onSecondary = useCallback(() => {
    window.dispatchEvent(new Event("recon-hero-secondary"));
  }, []);

  return (
    <div className="recon-hero-actions" role="group" aria-label="Hero actions">
      <button className="recon-btn-primary" type="button" onClick={onPrimary}>
        Upload Files
      </button>

      <button
        className="recon-btn-secondary"
        type="button"
        onClick={onSecondary}
      >
        Connect SAP
      </button>

      <button
        className="recon-btn-secondary"
        type="button"
        onClick={onSecondary}
      >
        Start Reconciliation
      </button>
    </div>
  );
}

export default HeroActions;

