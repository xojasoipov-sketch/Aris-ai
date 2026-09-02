"use client";

/** Ovoz to'lqin vizualizatsiyasi — Web Audio AnalyserNode'ga tayyor tuzilma.
 *
 * `analyser` prop berilsa — haqiqiy mikrofon chastota ma'lumoti chiziladi
 * (getByteFrequencyData). Berilmasa — silliq demo ma'lumot (sinus + noise),
 * `active` bo'lganda ko'tariladi, bo'lmaganda pasayadi.
 *
 * Canvas 2D — 48 ta simmetrik ustun, --accent-blue → --accent-glow gradient.
 */

import { useEffect, useRef } from "react";

const BARS = 48;

export function Waveform({
  active,
  analyser,
  width = 320,
  height = 48,
  className = "",
}: {
  active: boolean;
  analyser?: AnalyserNode | null;
  width?: number;
  height?: number;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const levels = useRef<number[]>(new Array(BARS).fill(0.05));
  const phase = useRef(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);

    const freqData = analyser ? new Uint8Array(analyser.frequencyBinCount) : null;
    let raf = 0;
    let last = performance.now();

    const draw = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      phase.current += dt * 4;

      for (let i = 0; i < BARS; i++) {
        let target: number;
        if (analyser && freqData) {
          analyser.getByteFrequencyData(freqData);
          const bin = Math.floor((i / BARS) * freqData.length * 0.6);
          target = (freqData[bin] / 255) * (active ? 1 : 0.15);
        } else {
          // Demo: markazda balandroq, sinus + tasodifiy jonlilik
          const center = 1 - Math.abs(i - BARS / 2) / (BARS / 2);
          const s =
            0.3 +
            0.4 * Math.abs(Math.sin(phase.current + i * 0.35)) +
            0.3 * Math.abs(Math.sin(phase.current * 1.7 + i * 0.13));
          target = active ? center * s : 0.05;
        }
        levels.current[i] += (target - levels.current[i]) * Math.min(1, dt * 10);
      }

      ctx.clearRect(0, 0, width, height);
      const barW = (width / BARS) * 0.55;
      const gap = width / BARS;
      for (let i = 0; i < BARS; i++) {
        const h = Math.max(2, levels.current[i] * height * 0.92);
        const x = i * gap + (gap - barW) / 2;
        const y = (height - h) / 2;
        const grad = ctx.createLinearGradient(0, y, 0, y + h);
        grad.addColorStop(0, "#7DD3FC");
        grad.addColorStop(1, "#4C8DFF");
        ctx.fillStyle = grad;
        ctx.globalAlpha = 0.4 + levels.current[i] * 0.6;
        ctx.beginPath();
        ctx.roundRect(x, y, barW, h, barW / 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [active, analyser, width, height]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width, height }}
      className={className}
      aria-hidden
    />
  );
}
