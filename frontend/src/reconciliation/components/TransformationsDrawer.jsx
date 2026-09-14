// Right-side slide-out panel for Mapping Review, opened from the toggle on
// TransformationSpecStep — overlays the Recipe Editor instead of replacing it
// in place, so switching between reviewing pairing results and editing the
// recipe no longer loses your place in either one. Wraps MappingReviewBody,
// which owns all the actual KPI/search/table content.
import { useEffect } from "react";
import { X } from "lucide-react";
import MappingReviewBody from "./MappingReviewBody";

function MappingReviewDrawer({ open, onClose }) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  return (
    <>
      <div
        className={`ct-drawer-backdrop${open ? " is-open" : ""}`}
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        className={`ct-drawer${open ? " is-open" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label="Mapping Review"
        aria-hidden={!open}
      >
        <div className="ct-drawer__head">
          <h3 className="ct-drawer__title">Mapping Review</h3>
          <button
            type="button"
            className="ct-drawer__close"
            onClick={onClose}
            aria-label="Close Mapping Review"
          >
            <X size={18} />
          </button>
        </div>
        <div className="ct-drawer__body">
          <MappingReviewBody />
        </div>
      </aside>
    </>
  );
}

export default MappingReviewDrawer;
