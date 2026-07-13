import { useEffect, useRef } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

import HeroSection from "../components/HeroSection";
import UploadSection from "../components/UploadSection";

import "../index.css";
import "../styles/reconciliation.css";

gsap.registerPlugin(ScrollTrigger);

function ReconciliationPage() {
  const rootRef = useRef(null);


  useEffect(() => {
    const rootEl = rootRef.current;
    if (!rootEl) return;

    const ctx = gsap.context(() => {
      const prefersReduced =
        typeof window !== "undefined" &&
        window.matchMedia &&
        window.matchMedia("(prefers-reduced-motion: reduce)")
          .matches;

      const setFinal = () => {
        // Hero content is managed by CSS + SideRays readability.
        // Keep scroll reveal wrappers behavior stable.
        rootEl
          .querySelectorAll("[data-scroll-reveal-section]")
          .forEach((el) => gsap.set(el, { opacity: 1, y: 0 }));
      };


      if (prefersReduced) {
        setFinal();
        return;
      }

      // Cinematic load sequence (wrappers only)
      // Hero animation is removed because HeroSection includes its own layout.
      const summaryWrap = rootEl.querySelector("[data-scroll-reveal-summary-wrap]");
      const tableWrap = rootEl.querySelector("[data-scroll-reveal-table-wrap]");
      const downloadWrap = rootEl.querySelector(
        "[data-scroll-reveal-download-wrap]",
      );

      [summaryWrap, tableWrap, downloadWrap].forEach((el) => {
        if (!el) return;
        gsap.set(el, { opacity: 0, y: 18, filter: "blur(6px)" });
      });

      const tl = gsap.timeline({ defaults: { ease: "power3.out" } });
      tl.to(summaryWrap, { opacity: 1, y: 0, filter: "blur(0px)", duration: 0.85 }, "-0.1")
        .to(tableWrap, { opacity: 1, y: 0, filter: "blur(0px)", duration: 0.9 }, "-0.05")
        .to(downloadWrap, { opacity: 1, y: 0, filter: "blur(0px)", duration: 0.75 }, "0.05");

      // Scroll reveals for remaining sections (animate wrappers only)
      const wrappers = rootEl.querySelectorAll("[data-scroll-reveal-section]");

      wrappers.forEach((el) => {
        gsap.set(el, { opacity: 0, y: 30 });
        ScrollTrigger.create({
          trigger: el,
          start: "top 86%",
          once: true,
          onEnter: () => {
            gsap.to(el, {
              opacity: 1,
              y: 0,
              duration: 0.9,
              ease: "power3.out",
              overwrite: "auto",
            });
          },
        });
      });
    }, rootEl);

    return () => {
      ctx.revert();
      ScrollTrigger.getAll().forEach((t) => t.kill());
      gsap.killTweensOf(rootEl);
    };
  }, []);

  return (
    <div ref={rootRef}>
      <HeroSection />

      <div data-scroll-reveal-summary-wrap className="recon-section" />

      <div data-scroll-reveal-table-wrap className="recon-section">
        <UploadSection />
      </div>

      <div data-scroll-reveal-download-wrap className="recon-foot" aria-hidden="true">
        <div className="recon-foot-line" />
      </div>
    </div>
  );
}

export default ReconciliationPage;










