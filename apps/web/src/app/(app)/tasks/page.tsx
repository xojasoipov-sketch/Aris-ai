"use client";

/** Vazifalar (/tasks) — FAZA 3 speci: Bugun/Kutilmoqda/Bajarilgan guruhlari,
 * checkbox + muddat vaqti. Belgilash lokal (real automation/executor keyin).
 */

import { Check } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";

import { ProgressRing } from "@/components/ui/cards";
import { Eyebrow, Panel } from "@/components/ui/primitives";
import { sound } from "@/lib/sound";

interface Task {
  id: number;
  title: string;
  due: string;
  group: "today" | "pending" | "done";
}

const INITIAL: Task[] = [
  { id: 1, title: "SMM strategiyani yangilash", due: "10:00", group: "today" },
  { id: 2, title: "Raqobatchilar tahlili", due: "12:30", group: "today" },
  { id: 3, title: "Loyiha ko'rigi", due: "14:00", group: "today" },
  { id: 4, title: "Mijoz uchun taklif tayyorlash", due: "Ertaga", group: "pending" },
  { id: 5, title: "Zaxira nusxasini tekshirish", due: "Juma", group: "pending" },
  { id: 6, title: "Kunlik briefing o'qildi", due: "08:00", group: "done" },
  { id: 7, title: "PR #42 ko'rib chiqildi", due: "09:15", group: "done" },
];

const GROUPS = [
  { key: "today", label: "Bugun" },
  { key: "pending", label: "Kutilmoqda" },
  { key: "done", label: "Bajarilgan" },
] as const;

export default function TasksPage() {
  const [tasks, setTasks] = useState(INITIAL);
  const done = tasks.filter((t) => t.group === "done").length;
  const percent = Math.round((done / tasks.length) * 100);

  const toggle = (id: number) => {
    sound.play("tick");
    setTasks((cur) =>
      cur.map((t) =>
        t.id === id
          ? { ...t, group: t.group === "done" ? "today" : ("done" as Task["group"]) }
          : t,
      ),
    );
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6 px-6 py-6 lg:px-8">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Vazifalar</h1>
        <div className="flex items-center gap-4">
          <div className="data text-right text-xs text-[var(--text-secondary)]">
            {done}/{tasks.length} bajarildi
          </div>
          <ProgressRing percent={percent} size={56} />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {GROUPS.map((g, gi) => {
          const items = tasks.filter((t) => t.group === g.key);
          return (
            <motion.div
              key={g.key}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.06 * gi, duration: 0.35, ease: "easeOut" }}
            >
              <Panel className="p-4">
                <div className="flex items-baseline justify-between">
                  <Eyebrow>{g.label}</Eyebrow>
                  <span className="data text-xs text-[var(--text-muted)]">{items.length}</span>
                </div>
                <div className="mt-3 space-y-1">
                  {items.length === 0 ? (
                    <p className="py-2 text-center text-xs text-[var(--text-muted)]">Bo'sh</p>
                  ) : (
                    items.map((t) => (
                      <button
                        key={t.id}
                        onClick={() => toggle(t.id)}
                        className="group flex w-full items-center gap-3 rounded-[10px] px-2 py-2 text-left transition-colors hover:bg-[var(--surface-hover)]"
                      >
                        <span
                          className={`flex h-4.5 w-4.5 shrink-0 items-center justify-center rounded-[5px] border transition-colors ${
                            t.group === "done"
                              ? "border-[var(--accent-blue)] bg-[var(--accent-blue)] text-[#050608]"
                              : "border-[var(--border-hairline)] group-hover:border-[var(--border-active)]"
                          }`}
                        >
                          {t.group === "done" ? <Check size={12} strokeWidth={2.5} /> : null}
                        </span>
                        <span
                          className={`flex-1 text-sm ${
                            t.group === "done"
                              ? "text-[var(--text-muted)] line-through"
                              : "text-[var(--text-primary)]"
                          }`}
                        >
                          {t.title}
                        </span>
                        <span className="data shrink-0 text-[11px] text-[var(--text-muted)]">
                          {t.due}
                        </span>
                      </button>
                    ))
                  )}
                </div>
              </Panel>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
