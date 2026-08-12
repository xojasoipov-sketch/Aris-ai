"use client";

/** Xabarlar (/messages) — FAZA 3 speci: chapda agent ro'yxati (oxirgi xabar
 * preview), o'ngda chat oynasi. Real Telegram tarixi keyin ulanadi.
 */

import { SendHorizontal } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";

import { NeuroOrb } from "@/components/core/NeuroOrb";
import { Panel } from "@/components/ui/primitives";
import { sound } from "@/lib/sound";

interface Thread {
  id: string;
  agent: string;
  preview: string;
  time: string;
  seed: number;
  messages: { from: "agent" | "owner"; text: string; time: string }[];
}

const THREADS: Thread[] = [
  {
    id: "ceo",
    agent: "CEO Agent",
    preview: "Haftalik strategik tahlil tayyor.",
    time: "23:40",
    seed: 1,
    messages: [
      { from: "agent", text: "Haftalik strategik tahlil tayyor. Asosiy xulosa: kanal o'sishi +12%, xarajat byudjet ichida.", time: "23:40" },
      { from: "owner", text: "Zo'r, asosiy raqamlarni yuborchi.", time: "23:42" },
      { from: "agent", text: "Yubordim — hisobot Fayllar bo'limida (Weekly Strategy Report, 2.4 MB).", time: "23:42" },
    ],
  },
  {
    id: "smm",
    agent: "SMM Agent",
    preview: "Yangi kontent-reja generatsiya qilindi.",
    time: "23:38",
    seed: 2,
    messages: [
      { from: "agent", text: "Yangi kontent-reja generatsiya qilindi — 7 kun, 12 post. Tasdiqlaysizmi?", time: "23:38" },
    ],
  },
  {
    id: "dev",
    agent: "Developer Agent",
    preview: "Kod ko'rigi yakunlandi.",
    time: "23:35",
    seed: 3,
    messages: [
      { from: "agent", text: "PR #42 ko'rigi yakunlandi: 2 izoh, CI yashil. Merge uchun tayyor.", time: "23:35" },
    ],
  },
  {
    id: "research",
    agent: "Research Agent",
    preview: "Bozor tahlili hisoboti.",
    time: "23:30",
    seed: 4,
    messages: [
      { from: "agent", text: "Bozor tahlili tayyor: 3 ta yangi raqobatchi aniqlandi, batafsil hisobot ilova qilindi.", time: "23:30" },
    ],
  },
];

export default function MessagesPage() {
  const [activeId, setActiveId] = useState(THREADS[0].id);
  const [draft, setDraft] = useState("");
  const active = THREADS.find((t) => t.id === activeId) ?? THREADS[0];

  return (
    <div className="mx-auto max-w-6xl px-6 py-6 lg:px-8">
      <h1 className="text-xl font-semibold">Xabarlar</h1>

      <div className="mt-5 grid h-[calc(100vh-14rem)] gap-4 lg:grid-cols-[300px_1fr]">
        {/* Chap: threadlar */}
        <Panel className="overflow-y-auto p-2">
          {THREADS.map((t) => (
            <button
              key={t.id}
              onClick={() => {
                sound.play("tick");
                setActiveId(t.id);
              }}
              className={`flex w-full items-center gap-3 rounded-[10px] border-l-2 px-3 py-2.5 text-left transition-colors ${
                t.id === activeId
                  ? "border-[var(--accent-blue)] bg-[var(--surface-hover)]"
                  : "border-transparent hover:bg-[var(--surface-hover)]"
              }`}
            >
              <NeuroOrb state="idle" mini seedOffset={t.seed} className="h-9 w-9 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-sm text-[var(--text-primary)]">{t.agent}</span>
                  <span className="data shrink-0 text-[10px] text-[var(--text-muted)]">{t.time}</span>
                </div>
                <div className="truncate text-xs text-[var(--text-secondary)]">{t.preview}</div>
              </div>
            </button>
          ))}
        </Panel>

        {/* O'ng: chat */}
        <Panel className="flex flex-col overflow-hidden">
          <div className="flex items-center gap-3 border-b border-[var(--border-hairline)] px-4 py-3">
            <NeuroOrb state="idle" mini seedOffset={active.seed} className="h-8 w-8" />
            <span className="text-sm font-medium text-[var(--text-primary)]">{active.agent}</span>
          </div>

          <div className="flex-1 space-y-3 overflow-y-auto p-4">
            {active.messages.map((m, i) => (
              <motion.div
                key={`${active.id}-${i}`}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.25, ease: "easeOut" }}
                className={`flex ${m.from === "owner" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[75%] rounded-[14px] px-3.5 py-2 text-sm leading-relaxed ${
                    m.from === "owner"
                      ? "border border-[var(--border-active)] bg-[rgba(76,141,255,0.08)]"
                      : "border border-[var(--border-hairline)] bg-[var(--bg-base)]"
                  }`}
                >
                  {m.text}
                  <div className="data mt-1 text-right text-[10px] text-[var(--text-muted)]">
                    {m.time}
                  </div>
                </div>
              </motion.div>
            ))}
          </div>

          <div className="flex items-center gap-2 border-t border-[var(--border-hairline)] p-3">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && draft.trim()) {
                  sound.play("tick");
                  setDraft("");
                }
              }}
              placeholder="Xabar yozing…"
              className="flex-1 rounded-full border border-[var(--border-hairline)] bg-[var(--bg-base)] px-4 py-2 text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)] focus:border-[var(--border-active)]"
            />
            <button
              aria-label="Yuborish"
              disabled={!draft.trim()}
              className="rounded-full bg-[var(--accent-blue)] p-2.5 text-[#050608] transition-[filter] hover:brightness-110 disabled:opacity-40"
              onClick={() => {
                sound.play("tick");
                setDraft("");
              }}
            >
              <SendHorizontal size={16} strokeWidth={1.5} />
            </button>
          </div>
        </Panel>
      </div>
    </div>
  );
}
