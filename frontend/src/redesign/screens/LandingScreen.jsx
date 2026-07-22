import { useEffect, useRef } from "react";
import gsap from "gsap";
import { ArrowRight, ShieldCheck, Wand2, Layers, Database, GitCompareArrows } from "lucide-react";
import { Button } from "../components/Button";
import { Badge, TierBadge } from "../components/Badge";
import { cn } from "../lib/cn";

const FEATURES = [
  { icon: <GitCompareArrows className="h-5 w-5" />, title: "Two mapping engines", body: "Manual control with a shadow preview, or an auditable deterministic rule ladder — same contract, your choice." },
  { icon: <ShieldCheck className="h-5 w-5" />, title: "Approve data, never code", body: "Every transformation is previewed as before/after data and fingerprint-pinned before a run." },
  { icon: <Layers className="h-5 w-5" />, title: "Semantic confidence tiers", body: "VERY_HIGH to OUT_OF_SCOPE — one meaning, one color, on every screen." },
  { icon: <Database className="h-5 w-5" />, title: "SAP-native", body: "Metadata-driven fetch across S/4HANA and IBP OData services, out of the box." },
];

export function LandingScreen({ onEnter }) {
  const root = useRef(null);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const ctx = gsap.context(() => {
      gsap.from("[data-hero]", { opacity: 0, y: 16, duration: 0.6, stagger: 0.08, ease: "power3.out" });
      gsap.from("[data-mock]", { opacity: 0, y: 24, scale: 0.98, duration: 0.7, delay: 0.15, ease: "power3.out" });
      gsap.from("[data-feature]", { opacity: 0, y: 16, duration: 0.5, stagger: 0.06, delay: 0.3, ease: "power2.out" });
    }, root);
    return () => ctx.revert();
  }, []);

  return (
    <div ref={root} className="relative h-full overflow-y-auto bg-bg">
      {/* ambient background */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute left-1/2 top-[-10%] h-[420px] w-[720px] -translate-x-1/2 rounded-full bg-accent/15 blur-[120px]" />
        <div
          className="absolute inset-0 opacity-[0.4]"
          style={{
            backgroundImage:
              "linear-gradient(to right, var(--rdx-line) 1px, transparent 1px), linear-gradient(to bottom, var(--rdx-line) 1px, transparent 1px)",
            backgroundSize: "44px 44px",
            maskImage: "radial-gradient(ellipse 80% 50% at 50% 0%, #000 40%, transparent 100%)",
            WebkitMaskImage: "radial-gradient(ellipse 80% 50% at 50% 0%, #000 40%, transparent 100%)",
          }}
        />
      </div>

      {/* top bar */}
      <div className="relative mx-auto flex max-w-6xl items-center justify-between px-8 py-5">
        <div className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent text-on-accent shadow-e1">
            <span className="font-mono text-[13px] font-bold">DR</span>
          </div>
          <span className="text-[15px] font-semibold tracking-[-0.01em]">Data Recon</span>
        </div>
        <Button variant="secondary" size="sm" onClick={onEnter}>Open app <ArrowRight className="h-4 w-4" /></Button>
      </div>

      {/* hero */}
      <section className="relative mx-auto max-w-3xl px-8 pt-16 pb-10 text-center">
        <div data-hero className="mb-5 inline-flex">
          <Badge status="info" dot>SAP S/4HANA ↔ IBP reconciliation</Badge>
        </div>
        <h1 data-hero className="text-[44px] font-semibold leading-[1.05] tracking-[-0.03em] text-text sm:text-[52px]">
          Reconcile SAP data with<br />precision you can audit
        </h1>
        <p data-hero className="mx-auto mt-5 max-w-xl text-[16px] leading-relaxed text-muted">
          Map, transform, and compare S/4HANA sales orders against IBP plans — with confidence tiers, shadow previews, and a full evidence trail on every value.
        </p>
        <div data-hero className="mt-8 flex items-center justify-center gap-3">
          <Button variant="primary" size="lg" onClick={onEnter}>Start a reconciliation <ArrowRight className="h-[18px] w-[18px]" /></Button>
          <Button variant="secondary" size="lg">View a sample run</Button>
        </div>
      </section>

      {/* mock window */}
      <section className="relative mx-auto max-w-5xl px-8 pb-16">
        <div data-mock className="overflow-hidden rounded-2xl border border-line bg-surface shadow-e3">
          <div className="flex items-center gap-2 border-b border-line bg-surface-2 px-4 py-2.5">
            <span className="h-3 w-3 rounded-full bg-missing-solid/70" />
            <span className="h-3 w-3 rounded-full bg-medium-solid/70" />
            <span className="h-3 w-3 rounded-full bg-match-solid/70" />
            <span className="ml-3 font-mono text-[11px] text-muted">/reconciliation/mapping-review</span>
          </div>
          <div className="grid grid-cols-1 gap-4 p-6 md:grid-cols-[1.4fr_1fr]">
            <div className="rounded-xl border border-line">
              <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
                <span className="text-[13px] font-medium">Material → Product</span>
                <span className="font-mono text-[11px] text-muted">Material → PRDID</span>
              </div>
              <div className="divide-y divide-line/70">
                {[
                  ["000000004711", "PRD-4711", "very_high"],
                  ["MAT-COAT-02", "PRD-COAT2", "high"],
                  ["HOUSING-AL", "PRD-HOUS-AL", "medium"],
                  ["0000LEGACY99", "—", "none"],
                ].map(([s, t, tier]) => (
                  <div key={s} className="flex items-center gap-3 px-4 py-2.5 text-[12.5px]">
                    <span className="w-32 truncate font-mono text-text-secondary">{s}</span>
                    <ArrowRight className="h-3 w-3 text-faint" />
                    <span className="w-24 truncate font-mono text-text-secondary">{t}</span>
                    <span className="ml-auto"><TierBadge tier={tier} /></span>
                  </div>
                ))}
              </div>
            </div>
            <div className="flex flex-col gap-3">
              <div className="rounded-xl border border-line p-4">
                <p className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted">Match rate</p>
                <p className="mt-1 text-[30px] font-semibold tracking-[-0.02em] text-match-fg">95.0%</p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl border border-line p-3">
                  <p className="text-[22px] font-semibold text-mismatch-fg">214</p>
                  <p className="text-[11px] text-muted">Mismatches</p>
                </div>
                <div className="rounded-xl border border-line p-3">
                  <p className="text-[22px] font-semibold text-missing-fg">148</p>
                  <p className="text-[11px] text-muted">Missing</p>
                </div>
              </div>
              <div className="flex items-center gap-2 rounded-xl border border-line bg-surface-2/50 p-3">
                <Wand2 className="h-4 w-4 text-accent-text" />
                <span className="text-[12.5px] text-text-secondary">Shadow preview approved</span>
                <Badge status="match" dot className="ml-auto">Pinned</Badge>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* features */}
      <section className="relative mx-auto max-w-5xl px-8 pb-20">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map((f) => (
            <div key={f.title} data-feature className={cn("rounded-xl border border-line bg-surface p-5 shadow-e1")}>
              <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-accent-tint text-accent-text">{f.icon}</div>
              <h3 className="text-[14px] font-semibold text-text">{f.title}</h3>
              <p className="mt-1 text-[12.5px] leading-relaxed text-muted">{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      <footer className="relative border-t border-line py-6 text-center text-[12px] text-muted">
        Data Recon · SAP S/4HANA ↔ IBP reconciliation platform
      </footer>
    </div>
  );
}

export default LandingScreen;
