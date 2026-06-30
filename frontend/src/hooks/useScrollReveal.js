import { useEffect } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

/**
 * Animate section containers when they enter the viewport.
 * - animateOnce by default
 * - cleans up ScrollTriggers on unmount
 */
export function useScrollReveal({
  selector = "[data-scroll-reveal]",
  root = null,
  from = { opacity: 0, y: 40, scale: 0.98 },
  to = { opacity: 1, y: 0, scale: 1 },
  duration = 1,
  stagger = 0.08,
  ease = "power3.out",
  once = true,
} = {}) {
  useEffect(() => {
    const elements = Array.from(
      (root ?? document).querySelectorAll(selector) || [],
    );

    if (!elements.length) return;

    const triggers = [];

    elements.forEach((el, idx) => {
      const t = ScrollTrigger.create({
        trigger: el,
        start: "top 85%",
        onEnter: () => {
          gsap.to(el, {
            ...to,
            duration,
            ease,
            delay: idx * stagger,
            overwrite: "auto",
          });
          if (once) {
            t.kill(false);
          }
        },
      });

      triggers.push(t);
    });

    // Set initial state
    gsap.set(elements, from);

    return () => {
      triggers.forEach((t) => t.kill());
      // kill any tweens targeting elements
      gsap.killTweensOf(elements);
    };
  }, [
    selector,
    root,
    duration,
    stagger,
    ease,
    once,
    from,
    to,
  ]);
}


