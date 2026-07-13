// Draggable "curtain" comparison of the Original Source (left) against the
// Shadow Source (right), à la image-diff tools. Both panes render an
// identically-sized table so the clipped overlay aligns pixel-for-pixel; the
// vertical divider is dragged horizontally to reveal one side or the other.
//
// Left of the divider shows the Original values; right of the divider shows the
// transformed Shadow values with changed cells highlighted
// (green = added, yellow = modified, red = removed, blue = aggregated).
import { useCallback, useEffect, useRef, useState } from "react";

function cellText(value) {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

// One pane of the curtain. `variant` picks which side of each diff to render
// and which change kinds to highlight (the "after" pane highlights the
// transformed value; the "before" pane highlights values that were removed).
function DiffTable({ columns, diffs, variant }) {
  const highlightKinds =
    variant === "after"
      ? { added: "add", modified: "mod", aggregated: "agg" }
      : { removed: "del", modified: "mod" };

  return (
    <table className="curtain-table" aria-hidden={variant === "after" ? "true" : undefined}>
      <thead>
        <tr>
          {columns.map((col) => (
            <th key={col}>{col}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {diffs.map((row, ri) => (
          <tr key={ri}>
            {columns.map((col) => {
              const change = row.changes.find((c) => c.field === col);
              const value = change ? (variant === "after" ? change.after : change.before) : null;
              const tone = change && change.changed ? highlightKinds[change.kind] : null;
              return (
                <td key={col} className={tone ? `curtain-cell curtain-cell--${tone}` : "curtain-cell"}>
                  {cellText(value)}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function BeforeAfterCurtain({ columns, diffs }) {
  const [pos, setPos] = useState(50); // divider position, % of stage width
  const stageRef = useRef(null);
  const draggingRef = useRef(false);

  const updateFromClientX = useCallback((clientX) => {
    const stage = stageRef.current;
    if (!stage) return;
    const rect = stage.getBoundingClientRect();
    if (rect.width <= 0) return;
    const ratio = (clientX - rect.left) / rect.width;
    setPos(Math.min(100, Math.max(0, ratio * 100)));
  }, []);

  useEffect(() => {
    const onMove = (e) => {
      if (!draggingRef.current) return;
      const clientX = e.touches ? e.touches[0].clientX : e.clientX;
      updateFromClientX(clientX);
    };
    const onUp = () => {
      draggingRef.current = false;
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("touchmove", onMove, { passive: true });
    window.addEventListener("touchend", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("touchmove", onMove);
      window.removeEventListener("touchend", onUp);
    };
  }, [updateFromClientX]);

  const startDrag = () => {
    draggingRef.current = true;
  };

  const onKeyDown = (e) => {
    if (e.key === "ArrowLeft") setPos((p) => Math.max(0, p - 4));
    if (e.key === "ArrowRight") setPos((p) => Math.min(100, p + 4));
  };

  if (!diffs?.length) {
    return <p className="wizard-field__help">No rows to compare in this preview window.</p>;
  }

  return (
    <div className="curtain">
      <div className="curtain__legend">
        <span className="curtain__legend-item"><i className="curtain-swatch curtain-swatch--add" /> Added</span>
        <span className="curtain__legend-item"><i className="curtain-swatch curtain-swatch--mod" /> Modified</span>
        <span className="curtain__legend-item"><i className="curtain-swatch curtain-swatch--del" /> Removed</span>
        <span className="curtain__legend-item"><i className="curtain-swatch curtain-swatch--agg" /> Aggregated</span>
      </div>

      <div className="curtain__scroll">
        <div className="curtain__stage" ref={stageRef}>
          {/* Base layer: Original (before), full width. */}
          <div className="curtain__layer">
            <DiffTable columns={columns} diffs={diffs} variant="before" />
          </div>
          {/* Overlay layer: Shadow (after), revealed to the right of the divider. */}
          <div
            className="curtain__layer curtain__layer--after"
            style={{ clipPath: `inset(0 0 0 ${pos}%)` }}
          >
            <DiffTable columns={columns} diffs={diffs} variant="after" />
          </div>

          <div className="curtain__tag curtain__tag--left">Original Source</div>
          <div className="curtain__tag curtain__tag--right">Shadow Source</div>

          <div
            className="curtain__handle"
            style={{ left: `${pos}%` }}
            role="slider"
            tabIndex={0}
            aria-label="Comparison divider"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(pos)}
            onPointerDown={startDrag}
            onTouchStart={startDrag}
            onKeyDown={onKeyDown}
          >
            <span className="curtain__grip" />
          </div>
        </div>
      </div>
      <p className="wizard-field__help">Drag the divider (or use ← →) to compare original vs. shadow.</p>
    </div>
  );
}

export default BeforeAfterCurtain;
