"use client";

/** Boshqaruv (Dashboard) — mockup'dagi asosiy sahifa (docs/10 §4 #1).
 * Markazda assistant yadrosi, atrofida stat/agent/tizim panellari.
 */

import { motion } from "framer-motion";

import { AssistantHero } from "@/components/assistant/AssistantHero";
import { LiveApprovals } from "@/components/dashboard/LiveApprovals";
import { AgentListItem, Sparkline, StatCard } from "@/components/ui/cards";
import { GlassPanel, StatusDot, TechLabel } from "@/components/ui/primitives";

/* Demo ma'lumot — real endpoint'lar ulangunga qadar (agents ro'yxati
 * backend'dagi agents/builtin bilan bir xil — bu tasodif emas). */
const AGENTS = [
  { name: "CEO Agent", division: "Strategiya", status: "online" },
  { name: "SMM Agent", division: "Marketing", status: "working" },
  { name: "Developer Agent", division: "Texnologiya", status: "online" },
  { name: "Research Agent", division: "Intellekt", status: "thinking" },
  { name: "Finance Agent", division: "Moliya", status: "offline" },
] as const;

const stagger = {
  hidden: { opacity: 0, y: 14 },
  show: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: 0.08 * i, duration: 0.45, ease: "easeOut" as const },
  }),
};

export default function DashboardPage() {
  return (
    <div className="mx-auto max-w-6xl space-y-8 px-8 py-8">
      {/* Jonli approval'lar — bor bo'lsa eng tepada (diqqat talab qiladi) */}
      <LiveApprovals />

      <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
        {/* ── Markaz: assistant ── */}
        <motion.div
          variants={stagger}
          custom={0}
          initial="hidden"
          animate="show"
          className="flex flex-col items-center justify-center py-4"
        >
          <AssistantHero />
        </motion.div>

        {/* ── O'ng ustun ── */}
        <div className="space-y-4">
          <motion.div variants={stagger} custom={1} initial="hidden" animate="show">
            <GlassPanel className="p-4">
              <div className="flex items-center justify-between">
                <TechLabel>Tizim holati</TechLabel>
                <div className="flex items-center gap-1.5">
                  <StatusDot color="var(--state-online)" />
                  <span className="text-[11px] font-medium text-[var(--state-online)]">ONLAYN</span>
                </div>
              </div>
              <div className="tabular mt-3 grid grid-cols-3 gap-3 font-mono text-xs">
                {(
                  [
                    ["CPU", "24%"],
                    ["RAM", "41%"],
                    ["Disk", "32%"],
                  ] as const
                ).map(([k, v]) => (
                  <div key={k}>
                    <div className="text-[var(--text-muted)]">{k}</div>
                    <div className="mt-0.5 text-sm text-[var(--text-primary)]">{v}</div>
                  </div>
                ))}
              </div>
              <div className="mt-3">
                <Sparkline data={[22, 28, 24, 35, 30, 42, 38, 31, 44, 40, 36, 48]} width={252} height={36} />
              </div>
            </GlassPanel>
          </motion.div>

          <motion.div variants={stagger} custom={2} initial="hidden" animate="show">
            <GlassPanel className="p-3">
              <TechLabel className="px-2 pt-1">Faol agentlar</TechLabel>
              <div className="mt-1">
                {AGENTS.map((a) => (
                  <AgentListItem key={a.name} {...a} />
                ))}
              </div>
            </GlassPanel>
          </motion.div>
        </div>
      </div>

      {/* ── Pastki stat qatori ── */}
      <motion.div
        variants={stagger}
        custom={3}
        initial="hidden"
        animate="show"
        className="grid grid-cols-2 gap-4 md:grid-cols-4"
      >
        <StatCard label="Loyihalar" value={12} hint="faol" />
        <StatCard label="Agentlar" value={24} hint="onlayn" />
        <StatCard label="Vazifalar" value="68%" hint="bajarilgan" />
        <StatCard label="Tizim" value={87} hint="optimal" />
      </motion.div>
    </div>
  );
}
