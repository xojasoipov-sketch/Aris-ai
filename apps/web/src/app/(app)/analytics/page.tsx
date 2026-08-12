"use client";

/** Analitika (/analytics) — FAZA 4 speci: productivity trend (glow area),
 * focus time, bajarilgan vazifalar. Real manba: youtube/instagram/telegram
 * stats tool'lari keyin ulanadi.
 */

import { motion } from "motion/react";

import { AreaChart } from "@/components/ui/AreaChart";
import { ProgressRing, Sparkline } from "@/components/ui/cards";
import { Eyebrow, Panel } from "@/components/ui/primitives";

const WEEK = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"];
const PRODUCTIVITY = [62, 71, 68, 84, 79, 58, 74];
const CHANNELS = [
  { name: "Telegram kanal", metric: "+340 a'zo", trend: [12, 18, 15, 24, 30, 28, 34] },
  { name: "YouTube", metric: "12.4K ko'rish", trend: [40, 38, 52, 47, 61, 58, 72] },
  { name: "Instagram", metric: "+180 obunachi", trend: [8, 12, 10, 16, 14, 22, 19] },
] as const;

export default function AnalyticsPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-5 px-6 py-6 lg:px-8">
      <h1 className="text-xl font-semibold">Analitika</h1>

      <div className="grid gap-4 lg:grid-cols-[1fr_260px]">
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, ease: "easeOut" }}>
          <Panel className="p-5">
            <div className="flex items-baseline justify-between">
              <Eyebrow>Unumdorlik trendi — hafta</Eyebrow>
              <span className="data text-xs text-[var(--text-secondary)]">o'rtacha 71%</span>
            </div>
            <div className="mt-4 overflow-x-auto">
              <AreaChart data={PRODUCTIVITY} labels={[...WEEK]} width={620} height={200} id="prod" />
            </div>
          </Panel>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.07, duration: 0.35, ease: "easeOut" }} className="space-y-4">
          <Panel className="flex items-center justify-between px-5 py-4">
            <div>
              <Eyebrow>Fokus vaqti</Eyebrow>
              <div className="data mt-1 text-2xl font-semibold text-[var(--text-primary)]">28h</div>
              <div className="text-xs text-[var(--text-secondary)]">bu hafta</div>
            </div>
            <ProgressRing percent={75} size={64} />
          </Panel>
          <Panel className="px-5 py-4">
            <Eyebrow>Bajarilgan vazifalar</Eyebrow>
            <div className="data mt-1 text-2xl font-semibold text-[var(--text-primary)]">156</div>
            <div className="text-xs text-[var(--status-online)]">+12% o'tgan haftaga nisbatan</div>
          </Panel>
        </motion.div>
      </div>

      <Eyebrow className="pt-2">Kanallar (SMM agent manbalari)</Eyebrow>
      <div className="grid gap-4 md:grid-cols-3">
        {CHANNELS.map((c, i) => (
          <motion.div
            key={c.name}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.05 * i, duration: 0.35, ease: "easeOut" }}
          >
            <Panel className="px-5 py-4">
              <div className="text-sm text-[var(--text-primary)]">{c.name}</div>
              <div className="data mt-0.5 text-xs text-[var(--status-online)]">{c.metric}</div>
              <div className="mt-3">
                <Sparkline data={[...c.trend]} width={200} height={30} id={`ch-${i}`} />
              </div>
            </Panel>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
