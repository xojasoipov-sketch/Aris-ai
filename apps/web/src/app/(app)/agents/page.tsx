"use client";

/** Agentlar (/agents) — grid, har karta mini-NeuroOrb avatar bilan.
 *
 * Z44: ro'yxat endi backend `GET /agents` dan. Ilgari bu yerda oltita
 * QOTIRILGAN agent turardi — nomlari, rollari va holatlari qo'lda
 * yozilgan edi ("Finance Agent · offline", "HR Agent · paused"), holbuki
 * backendda 12 ta agent bor va ularning holati boshqacha.
 *
 * `working`/`thinking` holatlari ham olib tashlandi: backend "hozir
 * ishlayapti" degan jonli signal bermaydi, ya'ni ular sof to'qima edi.
 */

import { Bot } from "lucide-react";
import { motion } from "motion/react";

import { NeuroOrb, type OrbState } from "@/components/core/NeuroOrb";
import { EmptyState } from "@/components/ui/forms";
import { Eyebrow, Panel, StatusDot } from "@/components/ui/primitives";
import type { AgentDto } from "@/lib/api";
import { useAgents } from "@/lib/useAgents";

type UiStatus = "online" | "offline" | "paused";

const STATUS_META: Record<UiStatus, { color: string; label: string; orb: OrbState }> = {
  online: { color: "var(--status-online)", label: "Faol", orb: "idle" },
  paused: { color: "var(--status-offline)", label: "To'xtatilgan", orb: "offline" },
  offline: { color: "var(--status-offline)", label: "Faol emas", orb: "offline" },
};

/** Backend `AgentStatus` → UI holati (faqat backend asoslay oladigani). */
function toUiStatus(status: string): UiStatus {
  if (status === "active") return "online";
  if (status === "paused") return "paused";
  return "offline";
}

/** Kartaning ikkinchi qatori — agentning HAQIQIY ish tarixi. */
function runSummary(agent: AgentDto): string {
  if (agent.total_runs === 0) return "hali ishga tushmagan";
  const pct = Math.round(agent.success_rate * 100);
  return `${agent.total_runs} run · ${pct}% muvaffaqiyat`;
}

export default function AgentsPage() {
  const state = useAgents();
  const agents = state.kind === "ready" ? state.agents : [];

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-6 py-6 lg:px-8">
      <div className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">Agentlar</h1>
        <Eyebrow>
          {state.kind === "ready" ? `${agents.length} ta · registry` : "yuklanmoqda"}
        </Eyebrow>
      </div>

      {state.kind !== "ready" || agents.length === 0 ? (
        <Panel className="p-6">
          <EmptyState
            icon={Bot}
            title={state.kind === "loading" ? "Yuklanmoqda…" : "Agentlar topilmadi"}
            hint={state.kind === "error" ? state.message : "Backend registry bo'sh yoki ulanmagan"}
          />
        </Panel>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {agents.map((a, i) => {
            const meta = STATUS_META[toUiStatus(a.status)];
            return (
              <motion.div
                key={a.name}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.04 * i, duration: 0.35, ease: "easeOut" }}
              >
                <Panel className="flex h-full flex-col p-5">
                  <div className="flex items-start justify-between">
                    <NeuroOrb
                      state={meta.orb}
                      mini
                      seedOffset={i + 1}
                      className="h-14 w-14"
                    />
                    <div className="flex items-center gap-2">
                      <StatusDot color={meta.color} pulse={false} />
                      <span className="text-xs" style={{ color: meta.color }}>
                        {meta.label}
                      </span>
                    </div>
                  </div>
                  <div className="mt-3 flex-1">
                    <div className="text-sm font-medium text-[var(--text-primary)]">{a.name}</div>
                    <div className="mt-0.5 text-xs text-[var(--text-muted)]">{a.division}</div>
                    <p className="mt-2 text-xs leading-relaxed text-[var(--text-secondary)]">
                      {a.description}
                    </p>
                  </div>
                  <div className="mt-4 flex items-center justify-between border-t border-[var(--border-hairline)] pt-3">
                    <span className="data text-[11px] text-[var(--text-muted)]">
                      {runSummary(a)}
                    </span>
                    <span className="data text-[11px] text-[var(--text-muted)]">
                      {a.tool_allowlist.length} tool
                    </span>
                  </div>
                </Panel>
              </motion.div>
            );
          })}
        </div>
      )}
    </div>
  );
}
