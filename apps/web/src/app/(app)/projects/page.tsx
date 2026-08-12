"use client";

/** Loyihalar (/projects) — FAZA 3 speci: ro'yxat, progress bar, % badge. */

import { motion } from "motion/react";

import { Eyebrow, Panel } from "@/components/ui/primitives";

const PROJECTS = [
  { name: "ZET Core", desc: "AI tizim yadrosi", progress: 78, status: "Faol" },
  { name: "TG SMM AI", desc: "Ijtimoiy tarmoq avtomatlashtiruvi", progress: 65, status: "Faol" },
  { name: "Do'kon boti", desc: "E-commerce Telegram bot", progress: 92, status: "Yakunlanmoqda" },
  { name: "Kamera tizimi", desc: "IoT / Xavfsizlik", progress: 51, status: "Faol" },
  { name: "Personal OS", desc: "Unumdorlik quroli", progress: 33, status: "Boshlang'ich" },
] as const;

export default function ProjectsPage() {
  return (
    <div className="mx-auto max-w-4xl space-y-6 px-6 py-6 lg:px-8">
      <div className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">Loyihalar</h1>
        <Eyebrow>{PROJECTS.length} ta faol</Eyebrow>
      </div>

      <div className="space-y-3">
        {PROJECTS.map((p, i) => (
          <motion.div
            key={p.name}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.05 * i, duration: 0.35, ease: "easeOut" }}
          >
            <Panel className="flex items-center gap-5 px-5 py-4">
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-3">
                  <span className="truncate text-sm font-medium text-[var(--text-primary)]">
                    {p.name}
                  </span>
                  <span className="shrink-0 text-xs text-[var(--text-muted)]">{p.status}</span>
                </div>
                <div className="mt-0.5 truncate text-xs text-[var(--text-secondary)]">{p.desc}</div>
                <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-[var(--surface-hover)]">
                  <motion.div
                    className="h-full rounded-full bg-[var(--accent-blue)]"
                    initial={{ width: 0 }}
                    animate={{ width: `${p.progress}%` }}
                    transition={{ delay: 0.15 + 0.05 * i, duration: 0.7, ease: "easeOut" }}
                  />
                </div>
              </div>
              <span className="data shrink-0 rounded-full border border-[var(--border-hairline)] px-2.5 py-1 text-xs text-[var(--accent-blue)]">
                {p.progress}%
              </span>
            </Panel>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
