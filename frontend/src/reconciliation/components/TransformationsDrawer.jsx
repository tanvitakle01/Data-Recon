// Right-side slide-out panel holding the Transformations Editor, opened from
// the floating launcher on TransformationSpecStep. It overlays the field
// mapping rather than pushing it around, so opening and closing the editor
// never loses your place in the mapping table underneath.
//
// The editor is the drawer's only content — everything the step needs below
// the field mapping is the single Approve Transformations button.
import { useEffect } from "react";
import { X } from "lucide-react";
import TransformationsEditor from "./TransformationsEditor";

function TransformationsDrawer({
  open,
  onClose,
  steps,
  onChange,
  sourceColumns,
  onDraftSteps,
  children,
}) {
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
        className={`ct-drawer ct-drawer--wide${open ? " is-open" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label="Transformations Editor"
        aria-hidden={!open}
      >
        <div className="ct-drawer__head">
          <h3 className="ct-drawer__title">Transformations Editor</h3>
          <button
            type="button"
            className="ct-drawer__close"
            onClick={onClose}
            aria-label="Close Transformations Editor"
          >
            <X size={18} />
          </button>
        </div>
        <div className="ct-drawer__body">
          {/* Resolution status / proposed-operation notices from the mapping
              sheet, rendered by the parent — they describe these steps, so
              they belong beside them rather than on the page behind. */}
          {children}
          <TransformationsEditor
            steps={steps}
            onChange={onChange}
            sourceColumns={sourceColumns}
            onDraftSteps={onDraftSteps}
          />
        </div>
      </aside>
    </>
  );
}

export default TransformationsDrawer;
