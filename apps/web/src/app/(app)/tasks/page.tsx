"use client";

/** Vazifalar (/tasks) — HAQIQIY backend bilan (Z46.2).
 *
 * ILGARI NIMA BO'LGAN. Sahifa fayl ichidagi qotirilgan massivdan
 * chizilardi:
 *
 *     const INITIAL = [
 *       { id: 1, title: "SMM strategiyani yangilash", due: "10:00" },
 *       ...
 *     ]
 *
 * Belgilash faqat `useState` ichida qolardi — sahifani yangilash
 * hammasini tiklardi. Qo'shish/o'chirish umuman yo'q edi.
 *
 * Endi `GET/POST/PATCH/DELETE /tasks` orqali haqiqiy `task` jadvali
 * bilan ishlaydi va har o'zgarish saqlanadi.
 */

import { Check, Loader2, Plus, Trash2 } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";

import { ProgressRing } from "@/components/ui/cards";
import { EmptyState } from "@/components/ui/forms";
import { Button, Eyebrow, Panel } from "@/components/ui/primitives";
import { type TaskDto, type TaskStatus, api } from "@/lib/api";
import { sound } from "@/lib/sound";
import { useResource } from "@/lib/useResource";

/** Kanban guruhlari — backend `TaskStatus` bilan AYNAN mos. */
const GROUPS = [
  { key: "todo", label: "Bajarilishi kerak" },
  { key: "in_progress", label: "Jarayonda" },
  { key: "blocked", label: "To'siq bor" },
  { key: "done", label: "Bajarilgan" },
] as const satisfies readonly { key: TaskStatus; label: string }[];

export default function TasksPage() {
  // Avtomatik yangilash O'CHIQ: ega ro'yxatni tahrirlayotganda u
  // ostidan almashib ketmasligi kerak. O'zgarishdan keyin `reload()`.
  const { state, reload } = useResource(() => api.tasks.list());
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  const tasks = state.kind === "ready" ? state.data : [];
  const done = tasks.filter((t) => t.status === "done").length;
  const percent = tasks.length ? Math.round((done / tasks.length) * 100) : 0;

  const add = async () => {
    const title = draft.trim();
    if (!title || busy) return;
    setBusy(true);
    const res = await api.tasks.create({ title });
    if (res.ok) {
      setDraft("");
      await reload();
    } else {
      sound.play("error");
    }
    setBusy(false);
  };

  const toggle = async (task: TaskDto) => {
    sound.play("tick");
    const next: TaskStatus = task.status === "done" ? "todo" : "done";
    const res = await api.tasks.update(task.id, { status: next });
    if (res.ok) await reload();
    else sound.play("error");
  };

  const remove = async (task: TaskDto) => {
    sound.play("tick");
    const res = await api.tasks.remove(task.id);
    if (res.ok) await reload();
    else sound.play("error");
  };

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">Vazifalar</h1>
          <p className="mt-0.5 text-sm text-[var(--text-secondary)]">
            {state.kind === "ready"
              ? `${done} / ${tasks.length} bajarildi`
              : state.kind === "loading"
                ? "Yuklanmoqda…"
                : "Backend bilan aloqa yo'q"}
          </p>
        </div>
        {state.kind === "ready" && tasks.length > 0 ? (
          <ProgressRing percent={percent} />
        ) : null}
      </header>

      <Panel className="p-4">
        <Eyebrow>Yangi vazifa</Eyebrow>
        <div className="mt-3 flex gap-2">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void add();
            }}
            placeholder="Nima qilish kerak?"
            aria-label="Yangi vazifa nomi"
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
            title="Vazifalarni yuklab bo'lmadi"
            hint={state.message}
            action={
              <Button onClick={() => void reload()} variant="ghost">
                Qayta urinish
              </Button>
            }
          />
        </Panel>
      ) : null}

      {state.kind === "ready" && tasks.length === 0 ? (
        <Panel className="p-4">
          <EmptyState
            title="Hali vazifa yo'q"
            hint="Yuqoridagi maydonga yozib qo'shing — ZET ham o'zi qo'sha oladi."
          />
        </Panel>
      ) : null}

      {GROUPS.map(({ key, label }) => {
        const group = tasks.filter((t) => t.status === key);
        if (group.length === 0) return null;
        return (
          <Panel key={key} className="p-4">
            <Eyebrow>
              {label} · {group.length}
            </Eyebrow>
            <ul className="mt-3 space-y-1">
              {group.map((task, i) => (
                <motion.li
                  key={task.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.03, duration: 0.3, ease: "easeOut" }}
                  className="group flex items-center gap-3 rounded-[10px] px-2 py-2 transition-colors hover:bg-[var(--surface-hover)]"
                >
                  <button
                    onClick={() => void toggle(task)}
                    aria-label={
                      task.status === "done" ? "Bajarilmagan deb belgilash" : "Bajarildi deb belgilash"
                    }
                    className="flex h-5 w-5 shrink-0 items-center justify-center rounded-[6px] border border-[var(--border-hairline)] transition-colors hover:border-[var(--border-active)] focus-visible:border-[var(--border-active)]"
                    style={
                      task.status === "done"
                        ? { background: "var(--accent-blue)", borderColor: "var(--accent-blue)" }
                        : undefined
                    }
                  >
                    {task.status === "done" ? (
                      <Check size={12} strokeWidth={2} className="text-white" aria-hidden />
                    ) : null}
                  </button>

                  <span
                    className={`flex-1 text-sm ${
                      task.status === "done"
                        ? "text-[var(--text-muted)] line-through"
                        : "text-[var(--text-primary)]"
                    }`}
                  >
                    {task.title}
                  </span>

                  {task.assigned_agent ? (
                    <span className="data text-[10px] text-[var(--text-muted)]">
                      {task.assigned_agent}
                    </span>
                  ) : null}

                  <button
                    onClick={() => void remove(task)}
                    aria-label="Vazifani o'chirish"
                    className="opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
                  >
                    <Trash2
                      size={15}
                      strokeWidth={1.5}
                      className="text-[var(--text-muted)] hover:text-[var(--status-alert)]"
                      aria-hidden
                    />
                  </button>
                </motion.li>
              ))}
            </ul>
          </Panel>
        );
      })}
    </div>
  );
}
