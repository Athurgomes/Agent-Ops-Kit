import { useEffect, useRef } from "react";

export interface AsciiFieldProps {
  className?: string;
  mode?: "beam" | "ambient";
  density?: "normal" | "sparse";
}

const CHARS = " .:-=+*#%@";
const BEAM_PERIOD_MS = 8000;
const FRAME_INTERVAL_MS = 33;
const REDUCED_MOTION_ANGLE = Math.PI * 0.88;

// Precompute 24 quantized palette styles from faint #2563EB to subtle light-blue beam core.
const PALETTE: string[] = Array.from({ length: 24 }, (_, i) => {
  const t = i / 23;
  const alpha = 0.08 + t * 0.88;
  const highlight = t > 0.68 ? (t - 0.68) / 0.32 : 0;
  const r = Math.round(37 + (228 - 37) * highlight);
  const g = Math.round(99 + (240 - 99) * highlight);
  const b = Math.round(235 + (255 - 235) * highlight);
  return `rgba(${r}, ${g}, ${b}, ${alpha.toFixed(3)})`;
});

function wrapAngleDiff(a: number, b: number): number {
  let diff = a - b;
  while (diff > Math.PI) diff -= Math.PI * 2;
  while (diff < -Math.PI) diff += Math.PI * 2;
  return diff;
}

function drawAsciiFrame(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  elapsedMs: number,
  mode: "beam" | "ambient",
  density: "normal" | "sparse",
  isStatic: boolean,
) {
  ctx.fillStyle = "#0A0A0A";
  ctx.fillRect(0, 0, width, height);

  if (width <= 0 || height <= 0) return;

  const baseCell = width < 640 ? 22 : 15;
  const cell = density === "sparse" ? Math.round(baseCell * 1.35) : baseCell;
  const cols = Math.ceil(width / cell);
  const rows = Math.ceil(height / cell);
  const maxDim = Math.hypot(width, height) || 1;

  // Lighthouse origin sits in the negative space on the right on desktop, higher on mobile.
  const ox = width < 640 ? width * 0.72 : width * 0.76;
  const oy = width < 640 ? height * 0.28 : height * 0.44;
  const beamAngle = isStatic
    ? REDUCED_MOTION_ANGLE
    : ((elapsedMs % BEAM_PERIOD_MS) / BEAM_PERIOD_MS) * Math.PI * 2;
  const phase = (elapsedMs / 1000) * 0.9;

  // Subtle ambient radial halo behind the beacon source (strictly #2563EB).
  if (mode === "beam") {
    const glowR = Math.min(width, height) * 0.46;
    const grad = ctx.createRadialGradient(ox, oy, 0, ox, oy, glowR);
    grad.addColorStop(0, "rgba(37, 99, 235, 0.14)");
    grad.addColorStop(0.55, "rgba(37, 99, 235, 0.04)");
    grad.addColorStop(1, "rgba(37, 99, 235, 0)");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, width, height);
  }

  const fontSize = Math.max(10, Math.round(cell * 0.78));
  ctx.font = `600 ${fontSize}px "JetBrains Mono Variable", "JetBrains Mono", ui-monospace, Consolas, monospace`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";

  const xOffset = (width - cols * cell) * 0.5 + cell * 0.5;
  const yOffset = (height - rows * cell) * 0.5 + cell * 0.5;
  const originSigma2 = 2 * Math.pow(Math.min(width, height) * 0.14, 2);

  let lastStyle = "";

  for (let row = 0; row < rows; row++) {
    const y = yOffset + row * cell;
    const dy = y - oy;

    for (let col = 0; col < cols; col++) {
      const x = xOffset + col * cell;
      const dx = x - ox;
      const dist2 = dx * dx + dy * dy;
      const dist = Math.sqrt(dist2);

      const wave = 0.09 + 0.06 * Math.sin(col * 0.23 + row * 0.17 + phase);
      let val = wave;

      if (mode === "beam") {
        const angle = Math.atan2(dy, dx);
        const angDiff = wrapAngleDiff(angle, beamAngle);
        const beamCore = Math.exp(-(angDiff * angDiff) / 0.045);
        const beamHalo = Math.exp(-(angDiff * angDiff) / 0.28);
        const radial = Math.exp(-dist / (maxDim * 0.62));
        const originGlow = Math.exp(-dist2 / originSigma2);

        val = Math.min(1, wave + radial * (0.58 * beamHalo + 0.56 * beamCore) + 0.34 * originGlow);
      } else {
        const ripple = 0.5 + 0.5 * Math.sin(dist * 0.025 - phase * 1.4);
        val = Math.min(1, wave + 0.22 * ripple);
      }

      if (val < 0.05) continue;

      const charIdx = Math.min(CHARS.length - 1, Math.max(1, Math.floor(val * (CHARS.length - 1) + 0.25)));
      const palIdx = Math.min(PALETTE.length - 1, Math.max(0, Math.floor(val * (PALETTE.length - 1))));
      const style = PALETTE[palIdx];
      if (style !== lastStyle) {
        ctx.fillStyle = style;
        lastStyle = style;
      }
      ctx.fillText(CHARS[charIdx], x, y);
    }
  }
}

export function AsciiField({ className = "", mode = "beam", density = "normal" }: AsciiFieldProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { alpha: false });
    if (!ctx) return;

    const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    let reducedMotion = motionQuery.matches;
    let inViewport = true;
    let pageVisible = document.visibilityState === "visible";

    let cssWidth = 0;
    let cssHeight = 0;
    let rafId = 0;
    let lastDraw = 0;
    let startTime = performance.now();

    const syncSize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      cssWidth = Math.max(1, Math.round(rect.width));
      cssHeight = Math.max(1, Math.round(rect.height));
      const targetW = Math.max(1, Math.floor(cssWidth * dpr));
      const targetH = Math.max(1, Math.floor(cssHeight * dpr));
      if (canvas.width !== targetW || canvas.height !== targetH) {
        canvas.width = targetW;
        canvas.height = targetH;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const drawStatic = () => {
      syncSize();
      drawAsciiFrame(ctx, cssWidth, cssHeight, 0, mode, density, true);
    };

    const stopLoop = () => {
      if (rafId !== 0) {
        cancelAnimationFrame(rafId);
        rafId = 0;
      }
    };

    const tick = (now: number) => {
      rafId = 0;
      if (reducedMotion || !inViewport || !pageVisible) return;

      if (now - lastDraw >= FRAME_INTERVAL_MS) {
        lastDraw = now;
        drawAsciiFrame(ctx, cssWidth, cssHeight, now - startTime, mode, density, false);
      }
      rafId = requestAnimationFrame(tick);
    };

    const syncRunning = () => {
      if (reducedMotion) {
        stopLoop();
        drawStatic();
        return;
      }
      if (!inViewport || !pageVisible) {
        stopLoop();
        return;
      }
      if (rafId === 0) {
        lastDraw = 0;
        rafId = requestAnimationFrame(tick);
      }
    };

    syncSize();
    if (reducedMotion) {
      drawStatic();
    } else {
      drawAsciiFrame(ctx, cssWidth, cssHeight, 0, mode, density, false);
    }

    const resizeObserver = new ResizeObserver(() => {
      syncSize();
      if (reducedMotion) {
        drawStatic();
      } else {
        drawAsciiFrame(ctx, cssWidth, cssHeight, performance.now() - startTime, mode, density, false);
      }
    });
    resizeObserver.observe(canvas);

    const intersectionObserver = new IntersectionObserver(
      (entries) => {
        inViewport = entries[0]?.isIntersecting ?? true;
        syncRunning();
      },
      { threshold: 0 },
    );
    intersectionObserver.observe(canvas);

    const handleVisibility = () => {
      pageVisible = document.visibilityState === "visible";
      if (pageVisible) {
        startTime = performance.now() - ((lastDraw - startTime) % BEAM_PERIOD_MS);
      }
      syncRunning();
    };
    document.addEventListener("visibilitychange", handleVisibility);

    const handleMotionChange = (e: MediaQueryListEvent) => {
      reducedMotion = e.matches;
      syncRunning();
    };
    motionQuery.addEventListener("change", handleMotionChange);

    syncRunning();

    return () => {
      stopLoop();
      resizeObserver.disconnect();
      intersectionObserver.disconnect();
      document.removeEventListener("visibilitychange", handleVisibility);
      motionQuery.removeEventListener("change", handleMotionChange);
    };
  }, [mode, density]);

  return <canvas ref={canvasRef} aria-hidden="true" className={`pointer-events-none block ${className}`} />;
}
