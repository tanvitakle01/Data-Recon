import { useEffect, useRef } from "react";
import gsap from "gsap";

/**
 * Fade + rise entrance for a container's direct children (or [data-animate] els).
 * Respects prefers-reduced-motion (GSAP no-ops under the CSS kill-switch anyway,
 * but we also guard here so layout is never left mid-animation).
 */
export function useStagger(deps = [], { y = 10, stagger = 0.04, duration = 0.4 } = {}) {
  const ref = useRef(null);
  useEffect(() => {
    if (!ref.current) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const targets = ref.current.querySelectorAll("[data-animate]");
    const els = targets.length ? targets : ref.current.children;
    const ctx = gsap.context(() => {
      gsap.from(els, { opacity: 0, y, duration, stagger, ease: "power2.out", clearProps: "opacity,transform" });
    }, ref);
    return () => ctx.revert();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return ref;
}
