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
 * `GET /automation/stats`, `GET /system`). Manbasi yo'q panel — SOXTA
 * SON EMAS, ochiq "ulanmagan" holati (CLAUDE.md: "Halol holatlar").
 *
 * Z50.1: ega yuborgan JARVIS mockupidan ikkita panel qo'shildi —
 * Tezkor amallar va sparkline'li Tizim monitori. Mockupdagi GPU/TEMP
 * QO'SHILMADI: na brauzer, na server videokarta modelini yoki
 * haroratini o'lchaydi (Z50 qarori — nexus/page.tsx'dagi izohga qarang).
 */

import {
  Activity,
  Bot,
  FolderKanban,
  ListChecks,
  MessageSquare,
  Mic,
  ServerOff,
  Terminal as TerminalIcon,
} from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";

import { CommandBar } from "@/components/dashboard/CommandBar";
import { LiveApprovals } from "@/components/dashboard/LiveApprovals";
import {
  AgentListItem,
  type AgentStatus,
  Sparkline,
  StatCard,
} from "@/components/ui/cards";
import { EmptyState } from "@/components/ui/forms";
import { Eyebrow, Panel, StatusDot } from "@/components/ui/primitives";
import { api, type AgentDto } from "@/lib/api";
import { useAgents } from "@/lib/useAgents";
import { useAutomationStats } from "@/lib/useAutomationStats";
import { useBackendHealth } from "@/lib/useBackendHealth";
import { useMetricHistory } from "@/lib/useMetricHistory";
import { useResource } from "@/lib/useResource";

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

/** Tezkor amallar — mockupdagi "Quick Actions" ro'yxati.
 *
 * Har biri HAQIQIY sahifaga olib boradi (Next.js `Link`), tovush
 * chalib hech qayerga bormaydigan tugma emas. */
const QUICK_ACTIONS = [
  { href: "/tasks", label: "Yangi vazifa", icon: ListChecks },
  { href: "/projects", label: "Loyiha boshlash", icon: FolderKanban },
  { href: "/agents", label: "Agent yaratish", icon: Bot },
  { href: "/terminal", label: "Terminal ochish", icon: TerminalIcon },
  { href: "/nexus", label: "Ovozli buyruq", icon: Mic },
] as const;

function formatUptime(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  if (hours < 24) return `${hours} soat`;
  return `${Math.floor(hours / 24)} kun ${hours % 24} soat`;
}

export default function DashboardPage() {
  const health = useBackendHealth();
  const agentsState = useAgents();
  const stats = useAutomationStats();
  const system = useResource(() => api.system(), 5_000);
  const recentMessages = useResource(() => api.messages("web", 4), 20_000);

  const agents = agentsState.kind === "ready" ? agentsState.agents : [];
  const totals = agentTotals(agents);
  const automations =
    stats.kind === "ready"
      ? (stats.data.schedules?.active ?? 0) + (stats.data.triggers?.active ?? 0)
      : null;

  const metrics = system.state.kind === "ready" ? system.state.data : null;
  const cpuHistory = useMetricHistory(metrics?.cpu_percent ?? null);
  const memHistory = useMetricHistory(metrics?.memory_percent ?? null);

  const messages = recentMessages.state.kind === "ready" ? recentMessages.state.data : [];

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

      {/* Tezkor amallar */}
      <motion.div variants={enter} custom={2} initial="hidden" animate="show">
        <Panel className="p-3">
          <Eyebrow className="px-2 pt-1">Tezkor amallar</Eyebrow>
          <div className="mt-1 grid grid-cols-2 gap-1.5 sm:grid-cols-5">
            {QUICK_ACTIONS.map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                className="flex flex-col items-center gap-2 rounded-[10px] px-3 py-3 text-center transition-colors hover:bg-[var(--surface-hover)]"
              >
                <Icon
                  size={19}
                  strokeWidth={1.5}
                  className="text-[var(--text-secondary)]"
                  aria-hidden
                />
                <span className="text-[11px] leading-tight text-[var(--text-secondary)]">
                  {label}
                </span>
              </Link>
            ))}
          </div>
        </Panel>
      </motion.div>

      <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
        <div className="space-y-6">
          {/* So'nggi faoliyat */}
          <motion.div variants={enter} custom={3} initial="hidden" animate="show">
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

          {/* So'nggi xabarlar — /messages ning qisqa ko'rinishi */}
          <motion.div variants={enter} custom={4} initial="hidden" animate="show">
            <Panel className="overflow-hidden">
              <div className="flex items-baseline justify-between border-b border-[var(--border-hairline)] px-4 py-3">
                <Eyebrow>So'nggi xabarlar</Eyebrow>
                <Link
                  href="/messages"
                  className="text-[11px] text-[var(--accent-blue)] hover:underline"
                >
                  Hammasi
                </Link>
              </div>
              {recentMessages.state.kind === "ready" && messages.length > 0 ? (
                <ul className="divide-y divide-[var(--border-hairline)]">
                  {messages.map((m) => (
                    <li key={m.id} className="flex items-start gap-2.5 px-4 py-2.5">
                      <StatusDot
                        color={
                          m.role === "user" ? "var(--accent-blue)" : "var(--status-online)"
                        }
                      />
                      <p className="min-w-0 flex-1 truncate text-xs text-[var(--text-secondary)]">
                        {m.content}
                      </p>
                      <span className="data shrink-0 text-[10px] text-[var(--text-muted)]">
                        {new Date(m.created_at).toLocaleTimeString("uz-UZ", {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState
                  icon={MessageSquare}
                  title={
                    recentMessages.state.kind === "loading" ? "Yuklanmoqda…" : "Suhbat yo'q"
                  }
                  hint="Veb chatda yozing — shu yerda ko'rinadi"
                />
              )}
            </Panel>
          </motion.div>
        </div>

        {/* O'ng ustun */}
        <motion.div
          variants={enter}
          custom={5}
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

            {/* CPU/RAM — HAQIQATAN o'lchanadi (`GET /system`, psutil).
                GPU/TEMP yo'q: server ularni bermaydi. Sparkline
                brauzerda yig'ilgan qisqa tarix — sahifa yangilansa
                boshidan boshlanadi, bu ochiq holat. */}
            {health === "online" && metrics ? (
              <div className="mt-3 space-y-2.5">
                <div className="grid grid-cols-2 gap-2">
                  {(
                    [
                      ["CPU", metrics.cpu_percent, cpuHistory],
                      ["RAM", metrics.memory_percent, memHistory],
                    ] as const
                  ).map(([label, value, hist]) => (
                    <div
                      key={label}
                      className="flex items-center justify-between rounded-[8px] bg-[var(--bg-base)] px-2.5 py-2"
                    >
                      <div>
                        <div className="text-[10px] text-[var(--text-muted)]">{label}</div>
                        <div className="data text-sm text-[var(--text-primary)]">{value}%</div>
                      </div>
                      {hist.length >= 2 ? (
                        <Sparkline data={hist} width={44} height={20} id={label} />
                      ) : null}
                    </div>
                  ))}
                </div>
                <div className="data grid grid-cols-3 gap-2 text-xs">
                  {(
                    [
                      ["Disk", `${metrics.disk_percent}%`],
                      ["Uptime", formatUptime(metrics.uptime_seconds)],
                      ["Jadval", stats.kind === "ready" ? (stats.data.schedules?.active ?? 0) : "—"],
                    ] as const
                  ).map(([k, v]) => (
                    <div key={k} className="rounded-[8px] bg-[var(--bg-base)] px-2.5 py-2">
                      <div className="text-[var(--text-muted)]">{k}</div>
                      <div className="mt-0.5 text-[13px] text-[var(--text-primary)]">{v}</div>
                    </div>
                  ))}
                </div>
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
