import { useEffect, useRef } from "react";

const MONO_FONT = '"IBM Plex Mono", ui-monospace, monospace';
const FRAME_INTERVAL_MS = 38; // ~26 fps cap

type DrawFn = (
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  elapsedMs: number,
  isStatic: boolean,
) => void;

function useCanvasArt(draw: DrawFn, bg: string) {
  const ref = useRef<HTMLCanvasElement | null>(null);
  const drawRef = useRef<DrawFn>(draw);
  drawRef.current = draw;

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { alpha: false });
    if (!ctx) return;

    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    let reduced = mq.matches;
    let visible = true;
    let pageVisible = document.visibilityState === "visible";
    let cssW = 0;
    let cssH = 0;
    let rafId = 0;
    let lastDraw = 0;
    let start = performance.now();

    const syncSize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      cssW = Math.max(1, Math.round(rect.width));
      cssH = Math.max(1, Math.round(rect.height));
      const tw = Math.max(1, Math.floor(cssW * dpr));
      const th = Math.max(1, Math.floor(cssH * dpr));
      if (canvas.width !== tw || canvas.height !== th) {
        canvas.width = tw;
        canvas.height = th;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const renderFrame = (elapsedMs: number, isStatic: boolean) => {
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, cssW, cssH);
      if (cssW > 0 && cssH > 0) {
        drawRef.current(ctx, cssW, cssH, elapsedMs, isStatic);
      }
    };

    const stop = () => {
      if (rafId !== 0) {
        cancelAnimationFrame(rafId);
        rafId = 0;
      }
    };

    const tick = (now: number) => {
      rafId = 0;
      if (reduced || !visible || !pageVisible) return;
      if (now - lastDraw >= FRAME_INTERVAL_MS) {
        lastDraw = now;
        renderFrame(now - start, false);
      }
      rafId = requestAnimationFrame(tick);
    };

    const syncRun = () => {
      if (reduced) {
        stop();
        syncSize();
        renderFrame(0, true);
        return;
      }
      if (!visible || !pageVisible) {
        stop();
        return;
      }
      if (rafId === 0) {
        lastDraw = 0;
        rafId = requestAnimationFrame(tick);
      }
    };

    syncSize();
    renderFrame(0, reduced);

    const ro = new ResizeObserver(() => {
      syncSize();
      renderFrame(reduced ? 0 : performance.now() - start, reduced);
    });
    ro.observe(canvas);

    const io = new IntersectionObserver(
      (entries) => {
        visible = entries[0]?.isIntersecting ?? true;
        syncRun();
      },
      { threshold: 0 },
    );
    io.observe(canvas);

    const onVis = () => {
      pageVisible = document.visibilityState === "visible";
      if (pageVisible) start = performance.now() - Math.max(0, lastDraw - start);
      syncRun();
    };
    document.addEventListener("visibilitychange", onVis);

    const onMotion = (e: MediaQueryListEvent) => {
      reduced = e.matches;
      syncRun();
    };
    mq.addEventListener("change", onMotion);

    syncRun();

    return () => {
      stop();
      ro.disconnect();
      io.disconnect();
      document.removeEventListener("visibilitychange", onVis);
      mq.removeEventListener("change", onMotion);
    };
  }, [bg]);

  return ref;
}

// 1. Cena 3: Ondas horizontais de sinal com cristas em #2563EB
export function AsciiWaves({ className = "" }: { className?: string }) {
  const ref = useCanvasArt((ctx, w, h, elapsed, isStatic) => {
    const t = isStatic ? 1.2 : elapsed / 1000;
    const cellX = 11;
    const cellY = 16;
    const cols = Math.floor(w / cellX);
    const rows = Math.floor(h / cellY);
    ctx.font = `500 12px ${MONO_FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";

    for (let r = 0; r < rows; r++) {
      const y = (r + 0.5) * cellY + (h - rows * cellY) * 0.5;
      const ny = r / Math.max(1, rows - 1);
      for (let c = 0; c < cols; c++) {
        const x = (c + 0.5) * cellX + (w - cols * cellX) * 0.5;
        const wave1 = 0.5 + 0.28 * Math.sin(c * 0.22 - t * 2.1);
        const wave2 = 0.54 + 0.22 * Math.sin(c * 0.34 - t * 1.4 + 1.7);
        const d1 = Math.abs(ny - wave1);
        const d2 = Math.abs(ny - wave2);

        if (d1 < 0.11) {
          ctx.fillStyle = d1 < 0.045 ? "#2563EB" : "#0A0A0A";
          ctx.fillText(d1 < 0.045 ? "~" : "=", x, y);
        } else if (d2 < 0.1) {
          ctx.fillStyle = "#737373";
          ctx.fillText("-", x, y);
        } else if (r === Math.floor(rows * 0.85) && c % 4 === 0) {
          ctx.fillStyle = "#A3A3A3";
          ctx.fillText(".", x, y);
        }
      }
    }
  }, "#FFFFFF");

  return <canvas ref={ref} aria-hidden="true" className={`pointer-events-none block h-36 w-full ${className}`} />;
}

// 2. Cena 4: Lente de Fresnel com anéis concêntricos e prismas radiais girando
export function AsciiFresnel({ className = "" }: { className?: string }) {
  const ref = useCanvasArt((ctx, w, h, elapsed, isStatic) => {
    const angleShift = isStatic ? 0.35 : (elapsed / 1000) * 0.45;
    const cell = 13;
    const cols = Math.floor(w / cell);
    const rows = Math.floor(h / cell);
    const cx = w * 0.5;
    const cy = h * 0.5;
    const maxR = Math.min(w, h) * 0.45;
    ctx.font = `600 11px ${MONO_FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";

    for (let r = 0; r < rows; r++) {
      const y = (r + 0.5) * cell + (h - rows * cell) * 0.5;
      for (let c = 0; c < cols; c++) {
        const x = (c + 0.5) * cell + (w - cols * cell) * 0.5;
        const dx = x - cx;
        const dy = y - cy;
        const dist = Math.hypot(dx, dy);
        if (dist > maxR) continue;

        const norm = dist / Math.max(1, maxR);
        const theta = Math.atan2(dy, dx) - angleShift;
        const ring = Math.abs(((norm * 4.5) % 1) - 0.5);
        const spoke = Math.abs(Math.sin(theta * 4));

        if (dist < cell * 0.9) {
          ctx.fillStyle = "#2563EB";
          ctx.fillText("@", x, y);
        } else if (spoke < 0.14 && dist > cell * 1.1) {
          ctx.fillStyle = "#2563EB";
          ctx.fillText("*", x, y);
        } else if (ring < 0.12) {
          ctx.fillStyle = norm < 0.48 ? "#0A0A0A" : "#525252";
          ctx.fillText(ring < 0.055 ? "+" : ":", x, y);
        } else if (norm > 0.92) {
          ctx.fillStyle = "#A3A3A3";
          ctx.fillText(".", x, y);
        }
      }
    }
  }, "#F7F7F5");

  return <canvas ref={ref} aria-hidden="true" className={`pointer-events-none block h-56 w-full ${className}`} />;
}

// 3. Cena 5: Rosa dos ventos (N / L / S / O) com agulha #2563EB e setor bloqueado esmaecido
export function AsciiCompass({ className = "" }: { className?: string }) {
  const ref = useCanvasArt((ctx, w, h, elapsed, isStatic) => {
    const t = isStatic ? 0 : elapsed / 1000;
    const needleAngle = -Math.PI * 0.25 + (isStatic ? 0 : Math.sin(t * 0.9) * 0.18);
    const cell = 13;
    const cols = Math.floor(w / cell);
    const rows = Math.floor(h / cell);
    const cx = w * 0.5;
    const cy = h * 0.5;
    const radius = Math.min(w, h) * 0.4;
    ctx.font = `600 12px ${MONO_FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";

    for (let r = 0; r < rows; r++) {
      const y = (r + 0.5) * cell + (h - rows * cell) * 0.5;
      for (let c = 0; c < cols; c++) {
        const x = (c + 0.5) * cell + (w - cols * cell) * 0.5;
        const dx = x - cx;
        const dy = y - cy;
        const dist = Math.hypot(dx, dy);
        const angle = Math.atan2(dy, dx);
        const blocked = angle > 0.35 && angle < 1.85; // setor bloqueado SE/S

        if (dist < cell * 0.75) {
          ctx.fillStyle = "#2563EB";
          ctx.fillText("+", x, y);
          continue;
        }

        // Agulha apontando o rumo visível
        const diff = Math.abs(Math.atan2(Math.sin(angle - needleAngle), Math.cos(angle - needleAngle)));
        if (diff < 0.13 && dist < radius * 0.85) {
          ctx.fillStyle = "#2563EB";
          ctx.fillText(dist > radius * 0.65 ? ">" : "=", x, y);
          continue;
        }

        // Anel externo
        if (Math.abs(dist - radius) < cell * 0.55) {
          ctx.fillStyle = blocked ? "#525252" : "#D4D4D4";
          ctx.fillText(blocked ? "x" : ":", x, y);
          continue;
        }

        // Setor bloqueado esmaecido
        if (blocked && dist < radius * 0.88 && (r + c) % 2 === 0) {
          ctx.fillStyle = "#404040";
          ctx.fillText("/", x, y);
        }
      }
    }

    // Rótulos cardeais em pt-BR: N / L / S / O
    ctx.font = `600 13px ${MONO_FONT}`;
    ctx.fillStyle = "#FFFFFF";
    ctx.fillText("N", cx, cy - radius - 14);
    ctx.fillText("L", cx + radius + 14, cy);
    ctx.fillText("O", cx - radius - 14, cy);
    ctx.fillStyle = "#737373";
    ctx.fillText("S", cx, cy + radius + 14);
  }, "#0A0A0A");

  return <canvas ref={ref} aria-hidden="true" className={`pointer-events-none block h-56 w-full ${className}`} />;
}

// 4. Cena 6: Faixa telegráfica em código Morse animando em branco sobre #2563EB
const MORSE_STREAM = "..-. .- .-. --- .-..   ... .. -. .- .-..   .-.. .. -- .. - .   ";

export function AsciiMorse({ className = "" }: { className?: string }) {
  const ref = useCanvasArt((ctx, w, h, elapsed, isStatic) => {
    const step = isStatic ? 0 : Math.floor((elapsed / 1000) * 6);
    const cellX = 14;
    const cols = Math.floor(w / cellX);
    const midY = h * 0.52;

    // Linha de base cartográfica
    ctx.fillStyle = "rgba(255,255,255,0.35)";
    ctx.fillRect(0, midY + 12, w, 1);

    ctx.font = `600 13px ${MONO_FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";

    for (let c = 0; c < cols; c++) {
      const x = (c + 0.5) * cellX + (w - cols * cellX) * 0.5;
      const ch = MORSE_STREAM[(c + step) % MORSE_STREAM.length];
      if (ch === " ") {
        if (c % 6 === 0) {
          ctx.fillStyle = "rgba(255,255,255,0.45)";
          ctx.fillText("|", x, midY + 12);
        }
        continue;
      }
      ctx.fillStyle = "#FFFFFF";
      ctx.fillText(ch === "-" ? "=" : "·", x, midY);
    }
  }, "#2563EB");

  return <canvas ref={ref} aria-hidden="true" className={`pointer-events-none block h-14 w-full ${className}`} />;
}

// 5. Cena 7: Bandeiras de sinalização marítima em ASCII tremulando no mastro
export function AsciiSignalFlags({ className = "" }: { className?: string }) {
  const ref = useCanvasArt((ctx, w, h, elapsed, isStatic) => {
    const t = isStatic ? 0.5 : elapsed / 1000;
    const cellX = 11;
    const cellY = 15;
    const cols = Math.floor(w / cellX);
    const rows = Math.floor(h / cellY);
    const mastCol = 3;
    const flagW = Math.min(13, Math.max(8, cols - mastCol - 2));

    ctx.font = `600 12px ${MONO_FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";

    for (let r = 1; r < rows - 1; r++) {
      const y = (r + 0.5) * cellY + (h - rows * cellY) * 0.5;
      const mastX = (mastCol + 0.5) * cellX;
      ctx.fillStyle = "#0A0A0A";
      ctx.fillText(r === 1 ? "+" : "|", mastX, y);

      // Três faixas de bandeiras correspondentes aos 3 perfis
      const band = Math.floor(((r - 2) / Math.max(1, rows - 4)) * 3);
      const localRow = (r - 2) % Math.max(3, Math.floor((rows - 4) / 3));
      if (r >= 2 && band >= 0 && band < 3 && localRow < 3) {
        for (let c = 1; c <= flagW; c++) {
          const flutter = isStatic ? 0 : Math.round(Math.sin(t * 2.8 + c * 0.45 + band * 1.4) * 1.6);
          const x = (mastCol + c + 0.5) * cellX;
          const fy = y + flutter;
          const isBlue = (band === 1 && c <= flagW * 0.55) || (band === 0 && localRow === 1) || (band === 2 && (c + localRow) % 2 === 0);
          ctx.fillStyle = isBlue ? "#2563EB" : "#0A0A0A";
          const glyph = band === 0 ? "#" : band === 1 ? "=" : "+";
          ctx.fillText(glyph, x, fy);
        }
      }
    }
  }, "#FFFFFF");

  return <canvas ref={ref} aria-hidden="true" className={`pointer-events-none block h-48 w-full ${className}`} />;
}

// 6. Cena 8: Régua/sonda batimétrica cartográfica com pulso percorrendo a escala
const DEPTH_MARKS = ["00m", "10m", "20m", "30m", "40m", "50m"];

export function AsciiSounding({ className = "" }: { className?: string }) {
  const ref = useCanvasArt((ctx, w, h, elapsed, isStatic) => {
    const t = isStatic ? 0.35 : (elapsed / 1000) * 0.45;
    const pulseRow = Math.floor((t % 1) * 10);
    const cellX = 11;
    const cellY = 17;
    const cols = Math.floor(w / cellX);
    const rows = Math.min(10, Math.floor(h / cellY));

    ctx.font = `500 12px ${MONO_FONT}`;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";

    for (let r = 0; r < rows; r++) {
      const y = (r + 0.5) * cellY + (h - rows * cellY) * 0.5;
      const isPulse = r === pulseRow;
      if (r % 2 === 0) {
        const mark = DEPTH_MARKS[Math.min(DEPTH_MARKS.length - 1, Math.floor(r / 2))];
        ctx.fillStyle = isPulse ? "#2563EB" : "#4A4A4A";
        ctx.fillText(mark, 4, y);
      }

      const barStart = 42;
      const profileLen = Math.max(6, Math.floor((cols - 5) * (0.45 + 0.35 * Math.sin(r * 0.7 + 0.5))));
      for (let c = 0; c < profileLen; c++) {
        const x = barStart + c * cellX;
        if (x > w - 12) break;
        const isTip = c === profileLen - 1;
        ctx.fillStyle = isPulse ? "#2563EB" : isTip ? "#0A0A0A" : "#A3A3A3";
        ctx.fillText(isPulse ? (isTip ? ">" : "=") : isTip ? "|" : "-", x, y);
      }
    }
  }, "#F7F7F5");

  return <canvas ref={ref} aria-hidden="true" className={`pointer-events-none block h-44 w-full ${className}`} />;
}

// 7. Cena 9: Silhueta de farol e feixe varrendo o horizonte costeiro sobre #0A0A0A
const TOWER = [
  "    /\\    ",
  "   [##]   ",
  "   |::|   ",
  "   |  |   ",
  "  /|  |\\  ",
  " /_|__|\\_ ",
];

export function AsciiHorizon({ className = "" }: { className?: string }) {
  const ref = useCanvasArt((ctx, w, h, elapsed, isStatic) => {
    const t = isStatic ? 0.25 : elapsed / 1000;
    const sweepAngle = isStatic ? -0.14 : Math.sin(t * 0.85) * 0.22;
    const cellX = 11;
    const cellY = 16;
    const cols = Math.floor(w / cellX);
    const rows = Math.floor(h / cellY);
    const towerCol = Math.max(4, Math.floor(cols * 0.72));
    const lanternRow = Math.max(2, Math.floor(rows * 0.32));
    const lanternX = towerCol * cellX + 44;
    const lanternY = (lanternRow + 1.5) * cellY;
    const horizonRow = lanternRow + TOWER.length;

    ctx.font = `600 12px ${MONO_FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";

    // Feixe varrendo para a esquerda no horizonte
    for (let r = 0; r < rows; r++) {
      const y = (r + 0.5) * cellY;
      for (let c = 0; c < cols; c++) {
        const x = (c + 0.5) * cellX;
        if (r === horizonRow) {
          ctx.fillStyle = c % 3 === 0 ? "#737373" : "#404040";
          ctx.fillText(c % 2 === 0 ? "~" : "-", x, y);
          continue;
        }
        if (x < lanternX) {
          const dx = lanternX - x;
          const dy = y - lanternY;
          const angle = Math.atan2(dy, dx);
          const diff = Math.abs(angle - sweepAngle);
          if (diff < 0.14) {
            const distFade = Math.max(0, 1 - dx / Math.max(1, lanternX));
            ctx.fillStyle = diff < 0.055 ? "#2563EB" : "#FFFFFF";
            ctx.fillText(distFade > 0.55 ? "*" : diff < 0.06 ? ":" : ".", x, y);
          }
        }
      }
    }

    // Silhueta do farol
    ctx.textAlign = "left";
    TOWER.forEach((line, idx) => {
      const y = (lanternRow + idx + 0.5) * cellY;
      ctx.fillStyle = idx === 1 ? "#2563EB" : "#FFFFFF";
      ctx.fillText(line, towerCol * cellX, y);
    });
  }, "#0A0A0A");

  return <canvas ref={ref} aria-hidden="true" className={`pointer-events-none block h-48 w-full ${className}`} />;
}
