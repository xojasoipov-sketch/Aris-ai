"use client";

/** <AgentStatusChip /> — CLAUDE.md master tizim.
 *
 * Pill: chapda mini-NeuroOrb (28px, BITTA shader — seed/holat parametri
 * farqlaydi, 5 alohida animatsiya yozilmagan) + matn.
 * Eski StatusPill (qo'lda SVG nuqtalar) o'rnini bosadi — endi ikonka ham
 * haqiqiy 3D nuqta-bulut.
 */

import { motion } from "motion/react";

import { NeuroOrb, type OrbState } from "@/components/core/NeuroOrb";

export type ChipKind = "thinking" | "solving" | "working" | "listening" | "searching";

/* Chip turi → orb holati + seed (bir xil shader, har xil ko'rinish) */
const CHIP: Record<ChipKind, { orb: OrbState; seed: number; label: string }> = {
  thinking: { orb: "thinking", seed: 0, label: "O'ylayapman…" },
  solving: { orb: "thinking", seed: 3, label: "Yechyapman…" },
  working: { orb: "searching", seed: 5, label: "Ishlayapman…" },
  listening: { orb: "listening", seed: 7, label: "Eshityapman…" },
  searching: { orb: "searching", seed: 11, label: "Agent qidiryapti…" },
};

export function AgentStatusChip({ kind, label }: { kind: ChipKind; label?: string }) {
  const c = CHIP[kind];
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      className="inline-flex items-center gap-2.5 rounded-full border border-[var(--border-hairline)] bg-[var(--bg-elevated)] py-1.5 pl-2 pr-4 text-sm text-[var(--text-primary)]"
    >
      <NeuroOrb state={c.orb} mini seedOffset={c.seed} className="h-7 w-7" />
      {label ?? c.label}
    </motion.div>
  );
}
