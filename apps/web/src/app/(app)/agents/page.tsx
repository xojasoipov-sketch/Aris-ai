"use client";

/** Agentlar (/agents) — FAZA 3 speci: grid, har karta mini-NeuroOrb avatar,
 * rol, status, harakat tugmasi. Ro'yxat backend agents/builtin bilan mos.
 */

import { Play, Pause } from "lucide-react";
import { motion } from "motion/react";

import { NeuroOrb, type OrbState } from "@/components/core/NeuroOrb";
import { Eyebrow, Panel, StatusDot } from "@/components/ui/primitives";
import { sound } from "@/lib/sound";

interface AgentCard {
  name: string;
  role: string;
  division: string;
  status: "online" | "working" | "thinking" | "offline" | "paused";
  orb: OrbState;
  seed: number;
}

const AGENTS: AgentCard[] = [
  { name: "CEO Agent", role: "Strategik nazorat, kunlik briefing", division: "Boshqaruv", status: "online", orb: "idle", seed: 1 },
  { name: "SMM Agent", role: "Kontent, nashr, kanal analitikasi", division: "Marketing", status: "working", orb: "searching", seed: 2 },
  { name: "Developer Agent", role: "GitHub, PR ko'rik, CI nazorati", division: "Texnologiya", status: "online", orb: "idle", seed: 3 },
  { name: "Research Agent", role: "Internet razvedkasi, tahlil", division: "Intellekt", status: "thinking", orb: "thinking", seed: 4 },
  { name: "Finance Agent", role: "Xarajat nazorati, approval", division: "Moliya", status: "offline", orb: "offline", seed: 5 },
  { name: "HR Agent", role: "AI-jamoa nazorati, eval", division: "Boshqaruv", status: "paused", orb: "offline", seed: 6 },
];

const STATUS_META: Record<AgentCard["status"], { color: string; label: string; pulse: boolean }> = {
  online: { color: "var(--status-online)", label: "Onlayn", pulse: false },
  working: { color: "var(--status-working)", label: "Ishlayapti", pulse: true },
  thinking: { color: "var(--status-thinking)", label: "O'ylayapti", pulse: true },
  offline: { color: "var(--status-offline)", label: "Oflayn", pulse: false },
  paused: { color: "var(--status-offline)", label: "To'xtatilgan", pulse: false },
};

export default function AgentsPage() {
  return (
    <div className="mx-auto max-w-6xl space-y-6 px-6 py-6 lg:px-8">
      <div className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">Agentlar</h1>
        <Eyebrow>{AGENTS.length} ta · agents/builtin</Eyebrow>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {AGENTS.map((a, i) => {
          const s = STATUS_META[a.status];
          const running = a.status !== "offline" && a.status !== "paused";
          return (
            <motion.div
              key={a.name}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.05 * i, duration: 0.35, ease: "easeOut" }}
            >
              <Panel className="flex h-full flex-col p-5">
                <div className="flex items-start justify-between">
                  <NeuroOrb state={a.orb} mini seedOffset={a.seed} className="h-14 w-14" />
                  <div className="flex items-center gap-2">
                    <StatusDot color={s.color} pulse={s.pulse} />
                    <span className="text-xs" style={{ color: s.color }}>
                      {s.label}
                    </span>
                  </div>
                </div>
                <div className="mt-3 flex-1">
                  <div className="text-sm font-medium text-[var(--text-primary)]">{a.name}</div>
                  <div className="mt-0.5 text-xs text-[var(--text-muted)]">{a.division}</div>
                  <p className="mt-2 text-xs leading-relaxed text-[var(--text-secondary)]">{a.role}</p>
                </div>
                <div className="mt-4 flex items-center justify-end border-t border-[var(--border-hairline)] pt-3">
                  <button
                    aria-label={running ? `${a.name}ni to'xtatish` : `${a.name}ni ishga tushirish`}
                    className="flex items-center gap-2 rounded-full border border-[var(--border-hairline)] px-3.5 py-1.5 text-xs text-[var(--text-secondary)] transition-colors hover:border-[var(--border-active)] hover:text-[var(--text-primary)]"
                    onClick={() => sound.play("tick")}
                  >
                    {running ? (
                      <>
                        <Pause size={13} strokeWidth={1.5} /> To'xtatish
                      </>
                    ) : (
                      <>
                        <Play size={13} strokeWidth={1.5} /> Ishga tushirish
                      </>
                    )}
                  </button>
                </div>
              </Panel>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
