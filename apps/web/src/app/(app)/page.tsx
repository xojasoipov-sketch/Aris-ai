"use client";

/** Boshqaruv (Dashboard) — FAZA 1 speci (CLAUDE.md).
 * Markazda 440px NeuroOrb; atrofida 3 panel:
 *   System Status (CPU/RAM/Disk/GPU/Network radial + sparkline + harorat)
 *   Active Agents (5 agent, status chip)
 *   Quick Actions (5 tugma)
 * Ma'lumot real ko'rinishli namuna (lorem yo'q); real endpoint keyin ulanadi.
 */

import { BotMessageSquare, FolderPlus, ListPlus, Mic, ServerOff, Terminal } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useState } from "react";

import { AssistantHero } from "@/components/assistant/AssistantHero";
import { LiveApprovals } from "@/components/dashboard/LiveApprovals";
import { AgentListItem, RadialGauge, Sparkline } from "@/components/ui/cards";
import { EmptyState } from "@/components/ui/forms";
import { Button, Eyebrow, Panel, StatusDot } from "@/components/ui/primitives";
import { useBackendHealth } from "@/lib/useBackendHealth";

/* Backend agents/builtin bilan bir xil ro'yxat — tasodif emas */
const AGENTS = [
  { name: "CEO Agent", division: "Strategiya", status: "online" },
  { name: "SMM Agent", division: "Marketing", status: "working" },
  { name: "Developer Agent", division: "Texnologiya", status: "online" },
  { name: "Research Agent", division: "Intellekt", status: "thinking" },
  { name: "HR Agent", division: "Boshqaruv", status: "offline" },
] as const;

const QUICK_ACTIONS = [
  { icon: ListPlus, label: "Yangi vazifa" },
  { icon: FolderPlus, label: "Loyiha boshlash" },
  { icon: BotMessageSquare, label: "Agent yaratish" },
  { icon: Terminal, label: "Terminal ochish" },
  { icon: Mic, label: "Ovozli buyruq" },
] as const;

/* Jonli ko'rinadigan demo metrikalar — real /system/status keyin ulanadi */
function useLiveMetrics() {
  const [m, setM] = useState({ cpu: 24, ram: 41, disk: 32, gpu: 18, net: 120 });
  const [history, setHistory] = useState<number[]>([22, 28, 24, 35, 30, 42, 38, 31, 44, 40, 36, 48]);
  useEffect(() => {
    const t = setInterval(() => {
      setM((cur) => ({
        cpu: Math.max(5, Math.min(95, cur.cpu + (Math.random() - 0.5) * 8)),
        ram: Math.max(20, Math.min(90, cur.ram + (Math.random() - 0.5) * 4)),
        disk: cur.disk,
        gpu: Math.max(3, Math.min(95, cur.gpu + (Math.random() - 0.5) * 10)),
        net: Math.max(10, Math.min(400, cur.net + (Math.random() - 0.5) * 40)),
      }));
      setHistory((h) => [...h.slice(1), Math.max(5, Math.min(95, h[h.length - 1] + (Math.random() - 0.5) * 12))]);
    }, 2000);
    return () => clearInterval(t);
  }, []);
  return { m, history };
}

const enter = {
  hidden: { opacity: 0, y: 10 },
  show: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: 0.07 * i, duration: 0.35, ease: "easeOut" as const },
  }),
};

export default function DashboardPage() {
  const { m, history } = useLiveMetrics();
  const health = useBackendHealth();

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-8 py-6">
      <LiveApprovals />

      <div className="grid gap-6 lg:grid-cols-[280px_1fr_280px]">
        {/* ── Chap ustun: System Status (halol holat — real /health) ── */}
        <motion.div variants={enter} custom={1} initial="hidden" animate="show" className="space-y-4">
          <Panel className="p-4">
            <div className="flex items-center justify-between">
              <Eyebrow>System Status</Eyebrow>
              <div className="flex items-center gap-1.5">
                <StatusDot
                  color={
                    health === "online"
                      ? "var(--status-online)"
                      : health === "offline"
                        ? "var(--status-offline)"
                        : "var(--status-working)"
                  }
                  pulse={health === "checking"}
                />
                <span
                  className="text-[10px] font-medium"
                  style={{
                    color:
                      health === "online" ? "var(--status-online)" : "var(--text-muted)",
                  }}
                >
                  {health === "online" ? "ONLAYN" : health === "offline" ? "ULANMAGAN" : "TEKSHIRILMOQDA"}
                </span>
              </div>
            </div>
            {health === "online" ? (
              <>
                <div className="mt-4 grid grid-cols-3 gap-y-4">
                  <RadialGauge percent={m.cpu} label="CPU" value={`${Math.round(m.cpu)}%`} />
                  <RadialGauge percent={m.ram} label="RAM" value={`${Math.round(m.ram)}%`} />
                  <RadialGauge percent={m.disk} label="Disk" value={`${Math.round(m.disk)}%`} />
                  <RadialGauge percent={m.gpu} label="GPU" value={`${Math.round(m.gpu)}%`} />
                  <div className="col-span-2 flex flex-col items-center justify-center gap-1">
                    <span className="data text-sm text-[var(--text-primary)]">
                      {Math.round(m.net)} <span className="text-[var(--text-muted)]">Mbps</span>
                    </span>
                    <span className="eyebrow !text-[9px]">Tarmoq</span>
                  </div>
                </div>
                <div className="mt-4 border-t border-[var(--border-hairline)] pt-3">
                  <div className="flex items-baseline justify-between">
                    <Eyebrow>CPU trend</Eyebrow>
                    <span className="data text-xs text-[var(--text-muted)]">46°C</span>
                  </div>
                  <div className="mt-2">
                    <Sparkline data={history} width={232} height={34} id="cpu" />
                  </div>
                </div>
              </>
            ) : (
              <EmptyState
                icon={ServerOff}
                title="Backend ulanmagan"
                hint="apps/core serverini ishga tushiring — metrikalar avtomatik paydo bo'ladi"
              />
            )}
          </Panel>
        </motion.div>

        {/* ── Markaz: NeuroOrb ── */}
        <motion.div
          variants={enter}
          custom={0}
          initial="hidden"
          animate="show"
          className="flex flex-col items-center justify-center"
        >
          <AssistantHero />
        </motion.div>

        {/* ── O'ng ustun: Agents + Quick Actions ── */}
        <motion.div variants={enter} custom={2} initial="hidden" animate="show" className="space-y-4">
          <Panel className="p-3">
            <Eyebrow className="px-2 pt-1">Active Agents</Eyebrow>
            <div className="mt-1">
              {AGENTS.map((a) => (
                <AgentListItem key={a.name} {...a} />
              ))}
            </div>
          </Panel>

          <Panel className="p-4">
            <Eyebrow>Quick Actions</Eyebrow>
            <div className="mt-3 flex flex-col gap-1.5">
              {QUICK_ACTIONS.map(({ icon: I, label }) => (
                <Button key={label} className="justify-start gap-3 !px-3 text-left">
                  <I size={16} strokeWidth={1.5} className="text-[var(--accent-blue)]" />
                  {label}
                </Button>
              ))}
            </div>
          </Panel>
        </motion.div>
      </div>
    </div>
  );
}
