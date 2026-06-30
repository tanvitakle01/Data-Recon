import PropTypes from "prop-types";
import { useEffect, useMemo, useRef, useState } from "react";

function ScrollVelocity({ velocity = 18, numCopies = 8, items }) {
  const containerRef = useRef(null);
  const [enabled, setEnabled] = useState(true);


  const list = useMemo(() => {
    const base = items?.length
      ? items
      : [
          "Secure",
          "Explainable",
          "Deterministic",
          "Auditable",
          "Governed",
          "Transparent",
          "Trusted Data",
          "Accuracy",
          "Visibility",
          "Accountability",
          "Complete Traceability",
          "Faster Resolution",
          "Enterprise Ready",
          "AI Assisted",
        ];

    const copies = Math.max(1, numCopies);
    const out = [];
    for (let i = 0; i < copies; i++) out.push(...base);
    return out;
  }, [items, numCopies]);

  useEffect(() => {
    const prefersReduced =
      typeof window !== "undefined" &&
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // avoid setState in effect body by deferring
    window.setTimeout(() => setEnabled(!prefersReduced), 0);
  }, []);

  useEffect(() => {
    if (!enabled) return;
    const el = containerRef.current;
    if (!el) return;

    // Ensure initial transform baseline
    el.style.transform = "translate3d(0px,0,0)";


    let raf = null;
    let last = performance.now();
    let x = 0;

    const step = (now) => {
      const dt = now - last;
      last = now;

      // pixels per second scaled from velocity
      const pxPerSec = velocity * 6;
      x -= (pxPerSec * dt) / 1000;

      // wrap
      // We rely on the fact that we have enough copies to cover the width.
      if (el) {
        const w = el.scrollWidth / 2; // heuristic
        if (Math.abs(x) > w) x = 0;
        el.style.transform = `translate3d(${x}px,0,0)`;
      }

      raf = requestAnimationFrame(step);
    };

    raf = requestAnimationFrame(step);
    return () => {
      if (raf) cancelAnimationFrame(raf);
    };
  }, [enabled, velocity]);

  // items prop is optional; defaults are the enterprise trust ticker.


  return (
    <div className="recon-ticker" aria-label="Trust ticker">
      <div className="recon-ticker-inner" ref={containerRef}>
        {list.map((t, idx) => (
          <span className="recon-ticker-item" key={`${t}-${idx}`}>
            {t}
            {idx < list.length - 1 && (
              <span className="recon-ticker-sep" aria-hidden="true">
                •
              </span>
            )}
          </span>
        ))}
      </div>
    </div>
  );
}

ScrollVelocity.propTypes = {
  velocity: PropTypes.number,
  numCopies: PropTypes.number,
  items: PropTypes.arrayOf(PropTypes.string),
};

export default ScrollVelocity;

