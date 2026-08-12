"use client";

/** Status pill — docs/10 §3.3 (IMG_1693 referensi).
 *
 * Chip'lar backend RunEvent/ToolCall'ga map qilinadi:
 *   *.search → Searching · agent_factory.* → Agent shaping · STT → Agent listening
 */

import { motion } from "framer-motion";

export type PillKind = "thinking" | "searching" | "solving" | "shaping" | "listening";

const PILL_TEXT: Record<PillKind, string> = {
  thinking: "O'ylayapman....",
  searching: "Qidiryapman...",
  solving: "Yechyapman....",
  shaping: "Agent yaratilyapti...",
  listening: "Agent eshityapti...",
};

/** Har chip o'z ikonchasiga ega — nuqtali doira/uchburchak/klaster (SVG). */
function PillIcon({ kind }: { kind: PillKind }) {
  const dots: [number, number][] = [];
  const N = 12;
  for (let i = 0; i < N; i++) {
    const a = (i / N) * Math.PI * 2;
    dots.push([8 + 6 * Math.cos(a), 8 + 6 * Math.sin(a)]);
  }
  if (kind === "shaping") {
    // Uchburchak kontur (mockup: "Agent shaping")
    const tri: [number, number][] = [];
    for (let i = 0; i < 9; i++) {
      const t = i / 9;
      const side = Math.floor(t * 3);
      const f = (t * 3) % 1;
      const pts = [
        [8, 2],
        [14, 13],
        [2, 13],
      ] as const;
      const a = pts[side];
      const b = pts[(side + 1) % 3];
      tri.push([a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f]);
    }
    return (
      <motion.svg
        width="16"
        height="16"
        viewBox="0 0 16 16"
        animate={{ rotate: 360 }}
        transition={{ duration: 6, repeat: Infinity, ease: "linear" }}
      >
        {tri.map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r="0.9" fill="currentColor" />
        ))}
      </motion.svg>
    );
  }
  return (
    <motion.svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      animate={{ rotate: kind === "listening" ? 0 : 360 }}
      transition={{ duration: kind === "thinking" ? 3 : 8, repeat: Infinity, ease: "linear" }}
    >
      {dots.map(([x, y], i) => (
        <motion.circle
          key={i}
          cx={x}
          cy={y}
          r="0.9"
          fill="currentColor"
          animate={kind === "listening" ? { opacity: [0.3, 1, 0.3] } : undefined}
          transition={
            kind === "listening"
              ? { duration: 1.2, repeat: Infinity, delay: i * 0.1 }
              : undefined
          }
        />
      ))}
    </motion.svg>
  );
}

export function StatusPill({ kind, label }: { kind: PillKind; label?: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -6, scale: 0.96 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className="glass inline-flex items-center gap-2.5 rounded-full px-[18px] py-2.5 text-sm text-[var(--text-primary)]"
    >
      <span className="text-[var(--accent-cyan)]">
        <PillIcon kind={kind} />
      </span>
      {label ?? PILL_TEXT[kind]}
    </motion.div>
  );
}
