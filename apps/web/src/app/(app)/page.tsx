"use client";

/** Boshqaruv (Dashboard) — operatsion bosh sahifa.
 *
 * Z44: QOTIRILGAN MA'LUMOT OLIB TASHLANDI. Ilgari bu sahifada beshta
 * o'ylab topilgan agent, beshta soxta faoliyat qatori va "CPU 26% /
 * RAM 40% / Disk 32%" turardi. Ega buni ko'rib "ko'p joyi soxta" dedi —
 * haqli, chunki backendda 12 ta agent bor va CPU/RAM ko'rsatkichlarini
 * ZET umuman o'lchamaydi.
 *
 * Endi har bir raqam backend'dan keladi (`GET /agents`,
 * `GET /automation/stats`). Manbasi yo'q panel — SOXTA SON EMAS, ochiq
 * "ulanmagan" holati (CLAUDE.md: "Halol holatlar").
 */

import { motion } from "motion/react";
import { Activity, ServerOff } from "lucide-react";

import { CommandBar } from "@/components/dashboard/CommandBar";
import { LiveApprovals } from "@/components/dashboard/LiveApprovals";
import { AgentListItem, type AgentStatus, StatCard } from "@/components/ui/cards";
import { EmptyState } from "@/components/ui/forms";
import { Eyebrow, Panel, StatusDot } from "@/components/ui/primitives";
import type { AgentDto } from "@/lib/api";
import { useAgents } from "@/lib/useAgents";
import { useAutomationStats } from "@/lib/useAutomationStats";
import { useBackendHealth } from "@/lib/useBackendHealth";

/** Backend `AgentStatus` → UI holati.
 *
 * `working`/`thinking` ATAYLAB yo'q: backend "hozir ishlayapti" degan
 * jonli signal bermaydi, shuning uchun ularni ko'rsatish to'qima
 * bo'lardi — aynan shu ilgari sodir bo'lgan edi.
 */
function toUiStatus(backendStatus: string): AgentStatus {
  if (backendStatus === "active") return "online";
  if (backendStatus === "paused") return "paused";
  return "offline";
}

const enter = {
  hidden: { opacity: 0, y: 8 },
  show: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: 0.05 * i, duration: 0.3, ease: "easeOut" as const },
  }),
};

function agentTotals(agents: AgentDto[]) {
  const runs = agents.reduce((sum, a) => sum + a.total_runs, 0);
  const ok = agents.reduce((sum, a) => sum + a.successful_runs, 0);
  return {
    active: agents.filter((a) => a.status === "active").length,
    total: agents.length,
    runs,
    successPct: runs > 0 ? Math.round((ok / runs) * 100) : null,
  };
}

export default function DashboardPage() {
  const health = useBackendHealth();
  const agentsState = useAgents();
  const stats = useAutomationStats();

  const agents = agentsState.kind === "ready" ? agentsState.agents : [];
  const totals = agentTotals(agents);
  const automations =
    stats.kind === "ready"
      ? (stats.data.schedules?.active ?? 0) + (stats.data.triggers?.active ?? 0)
      : null;

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-6 py-6 lg:px-8">
      <LiveApprovals />

      {/* Buyruq paneli — asosiy ish quroli */}
      <motion.div variants={enter} custom={0} initial="hidden" animate="show">
        <CommandBar />
      </motion.div>

      {/* KPI qatori — hammasi backend'dan. Ma'lumot yo'q bo'lsa "—". */}
      <motion.div
        variants={enter}
        custom={1}
        initial="hidden"
        animate="show"
        className="grid grid-cols-2 gap-4 lg:grid-cols-4"
      >
        <StatCard
          label="Faol agentlar"
          value={agentsState.kind === "ready" ? `${totals.active}/${totals.total}` : "—"}
          hint={agentsState.kind === "ready" ? "registry'dan" : "yuklanmoqda"}
        />
        <StatCard
          label="Jami bajarilgan"
          value={agentsState.kind === "ready" ? totals.runs : "—"}
          hint="agent run'lari"
        />
        <StatCard
          label="Muvaffaqiyat"
          value={totals.successPct === null ? "—" : `${totals.successPct}%`}
          hint={totals.runs > 0 ? `${totals.runs} run'dan` : "hali run yo'q"}
        />
        <StatCard
          label="Avtomatlashtirish"
          value={automations ?? "—"}
          hint="faol jadval + trigger"
        />
      </motion.div>

      <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
        {/* So'nggi faoliyat */}
        <motion.div variants={enter} custom={2} initial="hidden" animate="show">
          <Panel className="overflow-hidden">
            <div className="flex items-baseline justify-between border-b border-[var(--border-hairline)] px-4 py-3">
              <Eyebrow>So'nggi faoliyat</Eyebrow>
            </div>
            {/* Backend hozircha run oqimini bermaydi. Ilgari bu yerda
                beshta o'ylab topilgan qator turardi — soxta faoliyat
                haqiqiy faoliyatdan farq qilmasdi va ega tizimni
                ishlayapti deb o'ylardi. */}
            <EmptyState
              icon={Activity}
              title="Faoliyat oqimi hali ulanmagan"
              hint="Backend run tarixi endpoint'i qo'shilgach shu yerda ko'rinadi"
            />
          </Panel>
        </motion.div>

        {/* O'ng ustun */}
        <motion.div
          variants={enter}
          custom={3}
          initial="hidden"
          animate="show"
          className="space-y-4"
        >
          <Panel className="p-3">
            <Eyebrow className="px-2 pt-1">Agentlar</Eyebrow>
            <div className="mt-1">
              {agentsState.kind === "ready" && agents.length > 0 ? (
                agents.map((a) => (
                  <AgentListItem
                    key={a.name}
                    name={a.name}
                    division={a.division}
                    status={toUiStatus(a.status)}
                  />
                ))
              ) : (
                <EmptyState
                  icon={ServerOff}
                  title={agentsState.kind === "loading" ? "Yuklanmoqda…" : "Agentlar yo'q"}
                  hint={
                    agentsState.kind === "error"
                      ? agentsState.message
                      : "Backend registry bo'sh yoki ulanmagan"
                  }
                />
              )}
            </div>
          </Panel>

          <Panel className="p-4">
            <div className="flex items-center justify-between">
              <Eyebrow>Tizim</Eyebrow>
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
                  className="text-xs"
                  style={{
                    color: health === "online" ? "var(--status-online)" : "var(--text-muted)",
                  }}
                >
                  {health === "online"
                    ? "Onlayn"
                    : health === "offline"
                      ? "Ulanmagan"
                      : "Tekshirilmoqda"}
                </span>
              </div>
            </div>

            {/* CPU/RAM/Disk OLIB TASHLANDI — ZET ularni o'lchamaydi va
                qotirilgan "26% / 40% / 32%" sof to'qima edi. O'rniga
                backend HAQIQATAN beradigan hisoblagichlar. */}
            {health === "online" && stats.kind === "ready" ? (
              <div className="data mt-3 grid grid-cols-3 gap-2 text-xs">
                {(
                  [
                    ["Jadval", stats.data.schedules?.active ?? 0],
                    ["Trigger", stats.data.triggers?.active ?? 0],
                    ["Kuzatuv", stats.data.watchers?.active ?? 0],
                  ] as const
                ).map(([k, v]) => (
                  <div key={k} className="rounded-[8px] bg-[var(--bg-base)] px-2.5 py-2">
                    <div className="text-[var(--text-muted)]">{k}</div>
                    <div className="mt-0.5 text-sm text-[var(--text-primary)]">{v}</div>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState
                icon={ServerOff}
                title="Backend ulanmagan"
                hint="apps/core serverini ishga tushiring"
              />
            )}
          </Panel>
        </motion.div>
      </div>
    </div>
  );
}
