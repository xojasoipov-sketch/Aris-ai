"use client";

/** Bildirishnoma kartasi — FAZA 5 speci: mini NeuroOrb + agent nomi +
 * qisqa xabar + vaqt + yopish. .floating uslub (blur ruxsat etilgan joy).
 */

import { X } from "lucide-react";
import { motion } from "motion/react";

import { NeuroOrb } from "@/components/core/NeuroOrb";

export interface NotificationData {
  id: string;
  agent: string;
  message: string;
  time: string;
  seed?: number;
}

export function NotificationCard({
  data,
  onClose,
}: {
  data: NotificationData;
  onClose: (id: string) => void;
}) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: 40, scale: 0.96 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: 40, scale: 0.96 }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
      className="floating flex w-80 items-start gap-3 p-3.5"
    >
      <NeuroOrb state="searching" mini seedOffset={data.seed ?? 9} className="h-10 w-10 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-sm font-medium text-[var(--text-primary)]">
            {data.agent}
          </span>
          <span className="data shrink-0 text-[10px] text-[var(--text-muted)]">{data.time}</span>
        </div>
        <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">{data.message}</p>
      </div>
      <button
        aria-label="Yopish"
        onClick={() => onClose(data.id)}
        className="shrink-0 rounded-md p-1 text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]"
      >
        <X size={14} strokeWidth={1.5} />
      </button>
    </motion.div>
  );
}
