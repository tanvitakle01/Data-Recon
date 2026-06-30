import PropTypes from "prop-types";
import { useEffect, useMemo, useRef } from "react";

/**
 * Atmospheric, extremely subtle ray field.
 * Note: UI-only implementation.
 */
function SideRays({
  speed = 1.2,
  rayColor1 = "#4F46E5",
  rayColor2 = "#60A5FA",
  intensity = 0.8,
  spread = 1.4,
  origin = "top-right",
  tilt = -8,
  saturation = 1.1,
  blend = 0.55,
  falloff = 2.4,
  opacity = 0.25,
}) {
  const canvasRef = useRef(null);
  const rafRef = useRef(null);

  const cfg = useMemo(
    () => ({
      speed,
      rayColor1,
      rayColor2,
      intensity,
      spread,
      origin,
      tilt,
      saturation,
      blend,
      falloff,
      opacity,
    }),
    [
      speed,
      rayColor1,
      rayColor2,
      intensity,
      spread,
      origin,
      tilt,
      saturation,
      blend,
      falloff,
      opacity,
    ],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const prefersReduced =
      typeof window !== "undefined" &&
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const resize = () => {
      const parent = canvas.parentElement;
      if (!parent) return;
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const rect = parent.getBoundingClientRect();
      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    resize();
    const onResize = () => resize();
    window.addEventListener("resize", onResize);

    let t0 = performance.now();

    const draw = (now) => {
      const parent = canvas.parentElement;
      if (!parent) return;

      const w = parent.clientWidth;
      const h = parent.clientHeight;

      // Clear with transparent fill (keeps subtle)
      ctx.clearRect(0, 0, w, h);

      // Atmospheric gradient mask so rays fade out smoothly
      const mask = ctx.createRadialGradient(
        w * 0.9,
        h * 0.1,
        Math.min(w, h) * 0.05,
        w * 0.9,
        h * 0.1,
        Math.min(w, h) * (0.95 + cfg.falloff * 0.08),
      );
      mask.addColorStop(0, `rgba(255,255,255,${cfg.opacity})`);
      mask.addColorStop(0.55, `rgba(255,255,255,${cfg.opacity * 0.45})`);
      mask.addColorStop(1, `rgba(255,255,255,0)`);

      // Ray field
      const angle = ((cfg.tilt * Math.PI) / 180) * -1; // slight correction
      const base = prefersReduced ? 0 : (now - t0) * 0.001 * cfg.speed;

      const rays = Math.floor(18 * cfg.spread);
      const grad = ctx.createLinearGradient(w * 0.7, 0, w, h);
      grad.addColorStop(0, cfg.rayColor1);
      grad.addColorStop(1, cfg.rayColor2);

      ctx.globalCompositeOperation = "source-over";

      for (let i = 0; i < rays; i++) {
        const p = i / Math.max(1, rays - 1);
        const x0 = w * (0.78 + p * 0.22);
        const y0 = h * (0.02 + (1 - p) * 0.18);

        const drift = prefersReduced ? 0 : Math.sin(base * 0.9 + p * 6.0) * 6;
        const len = h * (0.65 + p * 0.55);

        // Ray thickness
        const thickness = 0.5 + (1 - p) * 1.1 * cfg.intensity;

        // Fade per-ray
        const alpha = cfg.opacity * cfg.blend * (0.25 + (1 - p) * 0.75);

        ctx.save();
        ctx.translate(x0 + drift, y0);
        ctx.rotate(angle);

        // Slight saturation via color overlay approximation
        ctx.strokeStyle = grad;
        ctx.globalAlpha = alpha;
        ctx.lineWidth = thickness;
        ctx.lineCap = "round";

        // Draw ray as short bright line with gradient fade
        const rayGrad = ctx.createLinearGradient(0, 0, len, 0);
        rayGrad.addColorStop(0, `rgba(255,255,255,${0.22 * cfg.saturation})`);
        rayGrad.addColorStop(0.2, grad.toString());
        rayGrad.addColorStop(1, `rgba(255,255,255,0)`);
        ctx.strokeStyle = rayGrad;

        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.lineTo(len, 0);
        ctx.stroke();

        ctx.restore();
      }

      // Apply radial mask to fade into content
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = "destination-in";
      ctx.fillStyle = mask;
      ctx.fillRect(0, 0, w, h);

      // Reset
      ctx.globalCompositeOperation = "source-over";

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);

    return () => {
      window.removeEventListener("resize", onResize);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [cfg]);

  return (
    <div
      className="recon-side-rays"
      aria-hidden="true"
      style={{ opacity: cfg.opacity }}
    >
      <canvas ref={canvasRef} />
      <div className="recon-side-rays-fade" />
    </div>
  );
}

SideRays.propTypes = {
  speed: PropTypes.number,
  rayColor1: PropTypes.string,
  rayColor2: PropTypes.string,
  intensity: PropTypes.number,
  spread: PropTypes.number,
  origin: PropTypes.string,
  tilt: PropTypes.number,
  saturation: PropTypes.number,
  blend: PropTypes.number,
  falloff: PropTypes.number,
  opacity: PropTypes.number,
};

export default SideRays;

