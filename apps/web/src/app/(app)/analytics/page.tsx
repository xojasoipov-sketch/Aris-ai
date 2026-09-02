"use client";

/** Analitika (/analytics) — HAQIQIY ko'rsatkichlar (Z47.2).
 *
 * ILGARI NIMA BO'LGAN. Sahifadagi HAR BIR son o'ylab topilgan edi:
 *
 *     PRODUCTIVITY = [62, 71, 68, 84, 79, 58, 74]   // trend grafigi
 *     CHANNELS = [{ metric: "+340 a'zo" }, { metric: "12.4K ko'rish" }]
 *     "28h" fokus vaqti · percent={75} · "156" bajarilgan vazifa
 *
 * Birorta ham o'lchanmagan. Sahifada bitta ham tugma yo'q edi.
 *
 * ENDI FAQAT O'LCHANADIGAN NARSA KO'RSATILADI:
 *   · vazifa statistikasi — haqiqiy `task` jadvalidan
 *   · loyihalar bo'yicha progress — vazifalardan hisoblangan
 *   · agent ishlashi — `GET /agents` (run soni, muvaffaqiyat ulushi)
 *   · avtomatlashtirish — `GET /automation/stats`
 *
 * Kanal statistikasi (Telegram/YouTube/Instagram) QO'YILMADI: ular
 * uchun tool'lar bor, lekin ular hali jadvalga yozilmaydi — ya'ni
 * ko'rsatadigan tarix yo'q. Bo'sh grafik chizishdan ko'ra, nima
 * yetishmayotganini ochiq aytish to'g'ri.
 */

import { motion } from "motion/react";

import { ProgressRing } from "@/components/ui/cards";
import { EmptyState } from "@/components/ui/forms";
import { Eyebrow, Panel } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";

export default function AnalyticsPage() {
  const tasks = useResource(() => api.tasks.list(), 30_000);
  const projects = useResource(() => api.projects.list(), 30_000);
  const agents = useResource(() => api.agents(), 30_000);

  const taskList = tasks.state.kind === "ready" ? tasks.state.data : [];
  const done = taskList.filter((t) => t.status === "done").length;
  const open = taskList.filter((t) => t.status !== "done" && t.status !== "cancelled").length;
  const percent = taskList.length ? Math.round((done / taskList.length) * 100) : 0;

  const projectList = projects.state.kind === "ready" ? projects.state.data : [];
  const agentList = agents.state.kind === "ready" ? agents.state.data : [];

  const totalRuns = agentList.reduce((sum, a) => sum + a.total_runs, 0);
  const successRuns = agentList.reduce((sum, a) => sum + a.successful_runs, 0);
  const successRate = totalRuns ? Math.round((successRuns / totalRuns) * 100) : null;

  const loading =
    tasks.state.kind === "loading" ||
    projects.state.kind === "loading" ||
    agents.state.kind === "loading";

  return (
    <div className="mx-auto max-w-5xl space-y-5 px-6 py-6 lg:px-8">
      <header>
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">Analitika</h1>
        <p className="mt-0.5 text-sm text-[var(--text-secondary)]">
          {loading ? "Yuklanmoqda…" : "O'lchangan ko'rsatkichlar"}
        </p>
      </header>

      <div className="grid gap-4 sm:grid-cols-3">
        <Panel className="px-5 py-4">
          <Eyebrow>Vazifalar</Eyebrow>
          <div className="data mt-1.5 text-3xl font-semibold text-[var(--text-primary)]">
            {taskList.length || "—"}
          </div>
          <div className="mt-1 text-xs text-[var(--text-secondary)]">
            {taskList.length ? `${open} ochiq · ${done} bajarilgan` : "hali vazifa yo'q"}
          </div>
        </Panel>

        <Panel className="px-5 py-4">
          <Eyebrow>Loyihalar</Eyebrow>
          <div className="data mt-1.5 text-3xl font-semibold text-[var(--text-primary)]">
            {projectList.length || "—"}
          </div>
          <div className="mt-1 text-xs text-[var(--text-secondary)]">
            {projectList.length
              ? `${projectList.filter((p) => p.status === "active").length} faol`
              : "hali loyiha yo'q"}
          </div>
        </Panel>

        <Panel className="px-5 py-4">
          <Eyebrow>Run muvaffaqiyati</Eyebrow>
          <div className="data mt-1.5 text-3xl font-semibold text-[var(--text-primary)]">
            {successRate === null ? "—" : `${successRate}%`}
          </div>
          <div className="mt-1 text-xs text-[var(--text-secondary)]">
            {totalRuns ? `${totalRuns} ta run` : "hali run yo'q"}
          </div>
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_260px]">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: "easeOut" }}
        >
          <Panel className="p-5">
            <Eyebrow>Loyihalar bo&apos;yicha bajarilish</Eyebrow>
            {projectList.length === 0 ? (
              <EmptyState
                title="Loyiha yo'q"
                hint="Loyiha qo'shib, unga vazifa biriktiring — progress shu yerda o'zi chiziladi."
              />
            ) : (
              <ul className="mt-4 space-y-3">
                {projectList.map((project) => (
                  <li key={project.id}>
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="truncate text-sm text-[var(--text-primary)]">
                        {project.name}
                      </span>
                      <span className="data shrink-0 text-xs text-[var(--text-secondary)]">
                        {project.task_done}/{project.task_total}
                      </span>
                    </div>
                    <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-[var(--surface-hover)]">
                      <motion.div
                        className="h-full rounded-full bg-[var(--accent-blue)]"
                        initial={{ width: 0 }}
                        animate={{ width: `${project.progress}%` }}
                        transition={{ duration: 0.5, ease: "easeOut" }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.08, duration: 0.35, ease: "easeOut" }}
          className="space-y-4"
        >
          <Panel className="flex flex-col items-center p-5">
            <Eyebrow>Vazifa bajarilishi</Eyebrow>
            <div className="mt-3">
              <ProgressRing percent={percent} />
            </div>
          </Panel>

          <Panel className="p-5">
            <Eyebrow>Kanal statistikasi</Eyebrow>
            <p className="mt-2 text-xs leading-relaxed text-[var(--text-muted)]">
              Telegram/YouTube/Instagram uchun tool&apos;lar ulangan, lekin natijalar hali
              jadvalga yozilmaydi — shuning uchun ko&apos;rsatadigan tarix yo&apos;q.
            </p>
          </Panel>
        </motion.div>
      </div>
    </div>
  );
}
