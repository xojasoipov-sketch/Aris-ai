"use client";

/** Loyihalar (/projects) — HAQIQIY backend bilan (Z46.2).
 *
 * ILGARI NIMA BO'LGAN. Beshta o'ylab topilgan loyiha va o'ylab
 * topilgan foiz:
 *
 *     const PROJECTS = [
 *       { name: "ZET Core", progress: 78 },
 *       { name: "TG SMM AI", progress: 65 },
 *       ...
 *     ]
 *
 * Sahifada birorta ham tugma yo'q edi — faqat o'qib bo'ladigan
 * fantastika. Progress esa hech narsadan hisoblanmagan qo'l bilan
 * yozilgan son edi.
 *
 * Endi `progress` backend'da HAQIQIY vazifalardan hisoblanadi
 * (`task_done / task_total`) va loyiha qo'shish/o'chirish ishlaydi.
 */

import { FolderOpen, Loader2, Plus, Trash2 } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";

import { EmptyState } from "@/components/ui/forms";
import { Button, Eyebrow, Panel } from "@/components/ui/primitives";
import { type ProjectDto, api } from "@/lib/api";
import { sound } from "@/lib/sound";
import { useResource } from "@/lib/useResource";

export default function ProjectsPage() {
  const { state, reload } = useResource(() => api.projects.list());
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  const projects = state.kind === "ready" ? state.data : [];
  const active = projects.filter((p) => p.status === "active").length;

  const add = async () => {
    const name = draft.trim();
    if (!name || busy) return;
    setBusy(true);
    const res = await api.projects.create({ name });
    if (res.ok) {
      setDraft("");
      await reload();
    } else {
      sound.play("error");
    }
    setBusy(false);
  };

  const remove = async (project: ProjectDto) => {
    const res = await api.projects.remove(project.id);
    if (res.ok) await reload();
    else sound.play("error");
  };

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">Loyihalar</h1>
        <p className="mt-0.5 text-sm text-[var(--text-secondary)]">
          {state.kind === "ready"
            ? `${active} ta faol · ${projects.length} ta jami`
            : state.kind === "loading"
              ? "Yuklanmoqda…"
              : "Backend bilan aloqa yo'q"}
        </p>
      </header>

      <Panel className="p-4">
        <Eyebrow>Yangi loyiha</Eyebrow>
        <div className="mt-3 flex gap-2">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void add();
            }}
            placeholder="Loyiha nomi"
            aria-label="Yangi loyiha nomi"
            className="flex-1 rounded-[10px] border border-[var(--border-hairline)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)] focus-visible:border-[var(--border-active)]"
          />
          <Button
            onClick={() => void add()}
            disabled={!draft.trim() || busy}
            variant="primary"
            className="flex items-center gap-2"
          >
            {busy ? (
              <Loader2 size={16} strokeWidth={1.5} className="animate-spin" aria-hidden />
            ) : (
              <Plus size={16} strokeWidth={1.5} aria-hidden />
            )}
            Qo&apos;shish
          </Button>
        </div>
      </Panel>

      {state.kind === "error" ? (
        <Panel className="p-4">
          <EmptyState
            title="Loyihalarni yuklab bo'lmadi"
            hint={state.message}
            action={
              <Button onClick={() => void reload()} variant="ghost">
                Qayta urinish
              </Button>
            }
          />
        </Panel>
      ) : null}

      {state.kind === "ready" && projects.length === 0 ? (
        <Panel className="p-4">
          <EmptyState
            icon={FolderOpen}
            title="Hali loyiha yo'q"
            hint="Loyiha qo'shsangiz, vazifalarni unga biriktirib bo'ladi va progress o'zi hisoblanadi."
          />
        </Panel>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2">
        {projects.map((project, i) => (
          <motion.div
            key={project.id}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.04, duration: 0.3, ease: "easeOut" }}
          >
            <Panel className="group p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="truncate text-sm font-medium text-[var(--text-primary)]">
                    {project.name}
                  </h2>
                  <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
                    {project.task_total === 0
                      ? "Vazifa biriktirilmagan"
                      : `${project.task_done} / ${project.task_total} vazifa bajarildi`}
                  </p>
                </div>
                <button
                  onClick={() => void remove(project)}
                  aria-label={`${project.name} loyihasini o'chirish`}
                  className="shrink-0 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
                >
                  <Trash2
                    size={15}
                    strokeWidth={1.5}
                    className="text-[var(--text-muted)] hover:text-[var(--status-alert)]"
                    aria-hidden
                  />
                </button>
              </div>

              <div className="mt-4 flex items-center gap-3">
                <div
                  className="h-1 flex-1 overflow-hidden rounded-full bg-[var(--surface-hover)]"
                  role="progressbar"
                  aria-valuenow={project.progress}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label={`${project.name} bajarilishi`}
                >
                  <motion.div
                    className="h-full rounded-full bg-[var(--accent-blue)]"
                    initial={{ width: 0 }}
                    animate={{ width: `${project.progress}%` }}
                    transition={{ duration: 0.5, ease: "easeOut" }}
                  />
                </div>
                <span className="data w-9 text-right text-xs text-[var(--text-secondary)]">
                  {project.progress}%
                </span>
              </div>
            </Panel>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
