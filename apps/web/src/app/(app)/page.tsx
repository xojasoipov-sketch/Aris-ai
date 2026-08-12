"use client";

/** Boshqaruv (Dashboard) — operatsion bosh sahifa.
 *
 * Sifat standarti bo'yicha qayta qurildi: markaziy dekorativ sahna YO'Q —
 * buyruq paneli (kichik orb bilan) + KPI qatori + faoliyat jadvali +
 * agentlar/tizim ustuni. Har panel savol javob beradi: "hozir nima
 * bo'lyapti, menga nima kerak?"
 */

import { motion } from "motion/react";
import { ServerOff } from "lucide-react";

import { CommandBar } from "@/components/dashboard/CommandBar";
import { LiveApprovals } from "@/components/dashboard/LiveApprovals";
import { AgentListItem, Sparkline, StatCard } from "@/components/ui/cards";
import { EmptyState } from "@/components/ui/forms";
import { Eyebrow, Panel, StatusDot } from "@/components/ui/primitives";
import { useBackendHealth } from "@/lib/useBackendHealth";

/* Agentlar ro'yxati — backend agents/builtin registry bilan bir xil */
const AGENTS = [
  { name: "CEO Agent", division: "Strategiya", status: "online" },
  { name: "SMM Agent", division: "Marketing", status: "working" },
  { name: "Developer Agent", division: "Texnologiya", status: "online" },
  { name: "Research Agent", division: "Intellekt", status: "thinking" },
  { name: "HR Agent", division: "Boshqaruv", status: "offline" },
] as const;

/* So'nggi faoliyat — observability stream ulangunga qadar namuna */
const ACTIVITY = [
  { time: "13:02", agent: "SMM Agent", action: "telegram.channel_stats", ok: true, ms: 142 },
  { time: "12:58", agent: "Developer Agent", action: "github.read — PR #42", ok: true, ms: 480 },
  { time: "12:47", agent: "Research Agent", action: "web.search — bozor tahlili", ok: true, ms: 1240 },
  { time: "12:31", agent: "Finance Agent", action: "xarajat approval so'radi", ok: false },
  { time: "08:00", agent: "CEO Agent", action: "kunlik briefing yaratildi", ok: true, ms: 3400 },
] as const;

const enter = {
  hidden: { opacity: 0, y: 8 },
  show: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: 0.05 * i, duration: 0.3, ease: "easeOut" as const },
  }),
};

export default function DashboardPage() {
  const health = useBackendHealth();
  const activeAgents = AGENTS.filter((a) => a.status !== "offline").length;

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-6 py-6 lg:px-8">
      <LiveApprovals />

      {/* Buyruq paneli — asosiy ish quroli */}
      <motion.div variants={enter} custom={0} initial="hidden" animate="show">
        <CommandBar />
      </motion.div>

      {/* KPI qatori */}
      <motion.div
        variants={enter}
        custom={1}
        initial="hidden"
        animate="show"
        className="grid grid-cols-2 gap-4 lg:grid-cols-4"
      >
        <StatCard label="Faol agentlar" value={`${activeAgents}/${AGENTS.length}`} hint="registry'dan" />
        <StatCard label="Bugungi vazifalar" value="3/7" hint="2 tasi bajarildi" />
        <StatCard label="Loyihalar" value={5} hint="o'rtacha 64%" />
        <StatCard label="Kunlik sarf" value="$0.04" hint="$0.50 limitdan" />
      </motion.div>

      <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
        {/* So'nggi faoliyat — jadval */}
        <motion.div variants={enter} custom={2} initial="hidden" animate="show">
          <Panel className="overflow-hidden">
            <div className="flex items-baseline justify-between border-b border-[var(--border-hairline)] px-4 py-3">
              <Eyebrow>So'nggi faoliyat</Eyebrow>
              <span className="text-[11px] text-[var(--text-muted)]">
                namuna — observability keyin ulanadi
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <tbody>
                  {ACTIVITY.map((r) => (
                    <tr
                      key={`${r.time}-${r.action}`}
                      className="border-b border-[var(--border-hairline)] transition-colors last:border-0 hover:bg-[var(--surface-hover)]"
                    >
                      <td className="data whitespace-nowrap px-4 py-2.5 text-xs text-[var(--text-muted)]">
                        {r.time}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-[var(--text-primary)]">
                        {r.agent}
                      </td>
                      <td className="w-full px-3 py-2.5 text-[var(--text-secondary)]">
                        {r.action}
                      </td>
                      <td className="whitespace-nowrap px-4 py-2.5 text-right">
                        {r.ok ? (
                          <span className="data text-xs text-[var(--status-online)]">
                            OK{r.ms ? ` · ${r.ms}ms` : ""}
                          </span>
                        ) : (
                          <span className="data text-xs text-[var(--status-working)]">
                            kutilmoqda
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </motion.div>

        {/* O'ng ustun */}
        <motion.div variants={enter} custom={3} initial="hidden" animate="show" className="space-y-4">
          <Panel className="p-3">
            <Eyebrow className="px-2 pt-1">Agentlar</Eyebrow>
            <div className="mt-1">
              {AGENTS.map((a) => (
                <AgentListItem key={a.name} {...a} />
              ))}
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
            {health === "online" ? (
              <>
                <div className="data mt-3 grid grid-cols-3 gap-2 text-xs">
                  {(
                    [
                      ["CPU", "26%"],
                      ["RAM", "40%"],
                      ["Disk", "32%"],
                    ] as const
                  ).map(([k, v]) => (
                    <div key={k} className="rounded-[8px] bg-[var(--bg-base)] px-2.5 py-2">
                      <div className="text-[var(--text-muted)]">{k}</div>
                      <div className="mt-0.5 text-sm text-[var(--text-primary)]">{v}</div>
                    </div>
                  ))}
                </div>
                <div className="mt-3">
                  <Sparkline
                    data={[22, 28, 24, 35, 30, 42, 38, 31, 44, 40, 36, 48]}
                    width={252}
                    height={30}
                    id="sys"
                  />
                </div>
              </>
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
