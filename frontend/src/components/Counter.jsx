import PropTypes from "prop-types";
import { useEffect, useRef, useState } from "react";

function Counter({
  value = 0,
  fontSize = 34,
  gap = 2,
  textColor = "#0F172A",
  fontWeight = 700,
}) {
  const [display, setDisplay] = useState(0);
  const started = useRef(false);

  useEffect(() => {
    // Animate only once (per component instance). Subsequent value changes will not re-run.
    if (started.current) return;
    started.current = true;

    const target = Number(value ?? 0);
    const prefersReduced =
      typeof window !== "undefined" &&
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (prefersReduced) {
      // avoid setState in effect body by deferring
      window.setTimeout(() => setDisplay(target), 0);
      return;
    }

    const durationMs = 1000;
    const t0 = performance.now();

    const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

    let rafId = null;
    const tick = (now) => {
      const p = Math.min(1, (now - t0) / durationMs);
      const eased = easeOutCubic(p);
      const next = Math.round(target * eased);
      setDisplay(next);
      if (p < 1) rafId = requestAnimationFrame(tick);
    };

    rafId = requestAnimationFrame(tick);
    return () => {
      if (rafId) cancelAnimationFrame(rafId);
    };
  }, [value]);

  return (
    <span
      className="recon-counter"
      style={{
        fontSize,
        gap,
        color: textColor,
        fontWeight,
      }}
    >
      {display.toLocaleString()}
    </span>
  );
}

Counter.propTypes = {
  value: PropTypes.number,
  fontSize: PropTypes.number,
  gap: PropTypes.number,
  textColor: PropTypes.string,
  fontWeight: PropTypes.number,
};

export default Counter;

