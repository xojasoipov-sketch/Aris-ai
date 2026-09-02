"use client";

/** Taqvim (/calendar) — HAQIQIY hodisalar bilan (Z46.2).
 *
 * ILGARI NIMA BO'LGAN. Oy setkasi matematikasi to'g'ri edi, lekin
 * MAZMUNI butunlay o'ylab topilgan:
 *
 *   · Hodisa nuqtalari kun RAQAMIGA bog'langan qotirilgan to'plam
 *     edi, ya'ni AYNI nuqtalar har oyda va har yilda takrorlanardi.
 *   · Kun katakchasini bosish faqat tovush chalardi.
 *   · O'ng ustundagi "Bugungi jadval" beshta o'ylab topilgan
 *     uchrashuvni ko'rsatardi ("Mijoz bilan qo'ng'iroq 17:30").
 *
 * Endi hodisalar `GET /events` dan oy oralig'i bo'yicha olinadi,
 * kun bosilsa o'sha kunning hodisalari ko'rinadi va hodisa
 * qo'shish/o'chirish ishlaydi.
 */

import { ChevronLeft, ChevronRight, Loader2, Plus, Trash2 } from "lucide-react";
import { motion } from "motion/react";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/ui/forms";
import { Button, Eyebrow, Panel } from "@/components/ui/primitives";
import { type EventDto, api } from "@/lib/api";
import { sound } from "@/lib/sound";
import { useResource } from "@/lib/useResource";

const WEEKDAYS = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"];
const MONTHS = [
  "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
  "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr",
];

/** `2026-08-15T10:00:00Z` → mahalliy kun raqami. */
function dayOf(iso: string): number {
  return new Date(iso).getDate();
}

function timeOf(iso: string): string {
  return new Date(iso).toLocaleTimeString("uz-UZ", { hour: "2-digit", minute: "2-digit" });
}

export default function CalendarPage() {
  const today = new Date();
  const [view, setView] = useState({ y: today.getFullYear(), m: today.getMonth() });
  const [selected, setSelected] = useState<number>(today.getDate());
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  // Oy chegaralari — backend faqat shu oraliqni qaytaradi.
  const range = useMemo(() => {
    const start = new Date(view.y, view.m, 1);
    const end = new Date(view.y, view.m + 1, 0, 23, 59, 59);
    return { start: start.toISOString(), end: end.toISOString() };
  }, [view]);

  const { state, reload } = useResource(() => api.events.list(range));
  const events = state.kind === "ready" ? state.data : [];

  // Kun → hodisalar. Nuqtalar endi HAQIQIY hodisalardan chiziladi,
  // shuning uchun boshqa oyga o'tilganda ular o'zgaradi.
  const byDay = useMemo(() => {
    const map = new Map<number, EventDto[]>();
    for (const event of events) {
      const day = dayOf(event.starts_at);
      map.set(day, [...(map.get(day) ?? []), event]);
    }
    return map;
  }, [events]);

  const first = new Date(view.y, view.m, 1);
  const daysInMonth = new Date(view.y, view.m + 1, 0).getDate();
  const startOffset = (first.getDay() + 6) % 7; // Dushanba = 0
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

  const add = async () => {
    const title = draft.trim();
    if (!title || busy) return;
    setBusy(true);
    // Tanlangan kunning 09:00'i — vaqt tanlagich keyingi bosqich.
    const starts = new Date(view.y, view.m, selected, 9, 0);
    const res = await api.events.create({ title, starts_at: starts.toISOString() });
    if (res.ok) {
      setDraft("");
      await reload();
    } else {
      sound.play("error");
    }
    setBusy(false);
  };

  const remove = async (event: EventDto) => {
    const res = await api.events.remove(event.id);
    if (res.ok) await reload();
    else sound.play("error");
  };

  const dayEvents = byDay.get(selected) ?? [];

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-6 py-6 lg:px-8">
      <header>
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">Taqvim</h1>
        <p className="mt-0.5 text-sm text-[var(--text-secondary)]">
          {state.kind === "ready"
            ? `Shu oyda ${events.length} ta hodisa`
            : state.kind === "loading"
              ? "Yuklanmoqda…"
              : "Backend bilan aloqa yo'q"}
        </p>
      </header>

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
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
                      aria-label={`${d}-kun`}
                      aria-pressed={selected === d}
                      className={`data relative flex h-full w-full flex-col items-center justify-center rounded-[10px] text-sm transition-colors ${
                        isToday(d)
                          ? "bg-[var(--accent-blue)] font-semibold text-[#050608]"
                          : selected === d
                            ? "border border-[var(--border-active)] text-[var(--text-primary)]"
                            : "text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]"
                      }`}
                      onClick={() => {
                        sound.play("tick");
                        setSelected(d);
                      }}
                    >
                      {d}
                      {byDay.has(d) && !isToday(d) ? (
                        <span className="absolute bottom-1.5 h-1 w-1 rounded-full bg-[var(--accent-blue)]" />
                      ) : null}
                    </button>
                  ) : null}
                </div>
              ))}
            </div>
          </Panel>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08, duration: 0.35, ease: "easeOut" }} className="space-y-4">
          <Panel className="p-4">
            <Eyebrow>
              {selected}-{MONTHS[view.m].toLowerCase()}
            </Eyebrow>
            <div className="mt-3 space-y-1">
              {dayEvents.length === 0 ? (
                <p className="py-4 text-center text-xs text-[var(--text-muted)]">
                  Bu kunda hodisa yo&apos;q
                </p>
              ) : (
                dayEvents.map((event) => (
                  <div
                    key={event.id}
                    className="group flex items-baseline gap-3 rounded-[10px] px-2 py-2 transition-colors hover:bg-[var(--surface-hover)]"
                  >
                    <span className="data shrink-0 text-xs text-[var(--accent-blue)]">
                      {event.all_day ? "Kun bo'yi" : timeOf(event.starts_at)}
                    </span>
                    <span className="flex-1 text-sm text-[var(--text-primary)]">{event.title}</span>
                    <button
                      onClick={() => void remove(event)}
                      aria-label="Hodisani o'chirish"
                      className="opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
                    >
                      <Trash2
                        size={14}
                        strokeWidth={1.5}
                        className="text-[var(--text-muted)] hover:text-[var(--status-alert)]"
                        aria-hidden
                      />
                    </button>
                  </div>
                ))
              )}
            </div>

            <div className="mt-3 flex gap-2 border-t border-[var(--border-hairline)] pt-3">
              <input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void add();
                }}
                placeholder="Yangi hodisa"
                aria-label="Yangi hodisa nomi"
                className="min-w-0 flex-1 rounded-[10px] border border-[var(--border-hairline)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)] focus-visible:border-[var(--border-active)]"
              />
              <Button
                onClick={() => void add()}
                disabled={!draft.trim() || busy}
                variant="primary"
                aria-label="Hodisa qo'shish"
              >
                {busy ? (
                  <Loader2 size={16} strokeWidth={1.5} className="animate-spin" aria-hidden />
                ) : (
                  <Plus size={16} strokeWidth={1.5} aria-hidden />
                )}
              </Button>
            </div>
          </Panel>

          {state.kind === "error" ? (
            <Panel className="p-4">
              <EmptyState
                title="Hodisalarni yuklab bo'lmadi"
                hint={state.message}
                action={
                  <Button onClick={() => void reload()} variant="ghost">
                    Qayta urinish
                  </Button>
                }
              />
            </Panel>
          ) : null}
        </motion.div>
      </div>
    </div>
  );
}
