"use client";

/** Taqvim (/calendar) — FAZA 3 speci: oy grid + "Bugungi jadval" agenda.
 * Real automation/scheduler keyin ulanadi.
 */

import { ChevronLeft, ChevronRight } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";

import { Eyebrow, Panel } from "@/components/ui/primitives";
import { sound } from "@/lib/sound";

const WEEKDAYS = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"];
const MONTHS = [
  "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
  "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr",
];

/* Voqealar — kun raqamiga bog'langan demo (scheduler keyin) */
const EVENT_DAYS = new Set([3, 8, 12, 15, 19, 22, 26]);

const AGENDA = [
  { time: "08:00", title: "Kunlik briefing (CEO Agent)" },
  { time: "10:00", title: "SMM strategiya yangilash" },
  { time: "12:30", title: "Raqobatchilar tahlili" },
  { time: "14:00", title: "Loyiha ko'rigi" },
  { time: "17:30", title: "Mijoz bilan qo'ng'iroq" },
] as const;

export default function CalendarPage() {
  const today = new Date();
  const [view, setView] = useState({ y: today.getFullYear(), m: today.getMonth() });

  const first = new Date(view.y, view.m, 1);
  const daysInMonth = new Date(view.y, view.m + 1, 0).getDate();
  // Dushanba = 0 boshlanish
  const startOffset = (first.getDay() + 6) % 7;
  const cells: (number | null)[] = [
    ...Array.from({ length: startOffset }, () => null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];

  const isToday = (d: number) =>
    d === today.getDate() && view.m === today.getMonth() && view.y === today.getFullYear();

  const nav = (dir: -1 | 1) => {
    sound.play("tick");
    setView((v) => {
      const m = v.m + dir;
      if (m < 0) return { y: v.y - 1, m: 11 };
      if (m > 11) return { y: v.y + 1, m: 0 };
      return { ...v, m };
    });
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-6 py-6 lg:px-8">
      <h1 className="text-xl font-semibold">Taqvim</h1>

      <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
        {/* Oy grid */}
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, ease: "easeOut" }}>
          <Panel className="p-5">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-[var(--text-primary)]">
                {MONTHS[view.m]} {view.y}
              </span>
              <div className="flex gap-1">
                <button aria-label="Oldingi oy" onClick={() => nav(-1)} className="rounded-lg p-1.5 text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-hover)]">
                  <ChevronLeft size={16} strokeWidth={1.5} />
                </button>
                <button aria-label="Keyingi oy" onClick={() => nav(1)} className="rounded-lg p-1.5 text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-hover)]">
                  <ChevronRight size={16} strokeWidth={1.5} />
                </button>
              </div>
            </div>

            <div className="mt-4 grid grid-cols-7 gap-1 text-center">
              {WEEKDAYS.map((d) => (
                <div key={d} className="eyebrow py-1 !text-[9px]">
                  {d}
                </div>
              ))}
              {cells.map((d, i) => (
                <div key={i} className="aspect-square p-0.5">
                  {d ? (
                    <button
                      className={`data relative flex h-full w-full flex-col items-center justify-center rounded-[10px] text-sm transition-colors ${
                        isToday(d)
                          ? "bg-[var(--accent-blue)] font-semibold text-[#050608]"
                          : "text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]"
                      }`}
                      onClick={() => sound.play("tick")}
                    >
                      {d}
                      {EVENT_DAYS.has(d) && !isToday(d) ? (
                        <span className="absolute bottom-1.5 h-1 w-1 rounded-full bg-[var(--accent-blue)]" />
                      ) : null}
                    </button>
                  ) : null}
                </div>
              ))}
            </div>
          </Panel>
        </motion.div>

        {/* Bugungi jadval */}
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08, duration: 0.35, ease: "easeOut" }}>
          <Panel className="p-4">
            <Eyebrow>Bugungi jadval</Eyebrow>
            <div className="mt-3 space-y-1">
              {AGENDA.map((e) => (
                <div
                  key={e.time}
                  className="flex items-baseline gap-3 rounded-[10px] px-2 py-2 transition-colors hover:bg-[var(--surface-hover)]"
                >
                  <span className="data shrink-0 text-xs text-[var(--accent-blue)]">{e.time}</span>
                  <span className="text-sm text-[var(--text-primary)]">{e.title}</span>
                </div>
              ))}
            </div>
          </Panel>
        </motion.div>
      </div>
    </div>
  );
}
