"use client";

/** AI Yordamchi (/ai-chat) — FAZA 2 speci (CLAUDE.md).
 *
 * Markazda NeuroOrb (holat mashinasiga ulangan), ostida ovoz to'lqini
 * (Waveform — AnalyserNode'ga tayyor, hozircha demo signal), yuqorida
 * model/kontekst selektor, pastda chat oqimi + input.
 *
 * Model selektor ZET Model Router tier'larini ko'rsatadi (ADR-0006):
 * real /route endpoint keyin ulanadi.
 */

import { ChevronDown } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Waveform } from "@/components/assistant/Waveform";
import { NeuroOrb, type OrbState } from "@/components/core/NeuroOrb";
import { AgentStatusChip } from "@/components/ui/AgentStatusChip";
import { CommandInput } from "@/components/ui/CommandInput";
import {
  useAssistant,
  type AssistantState,
} from "@/lib/assistant-machine";

const TO_ORB: Record<AssistantState, OrbState> = {
  sleep: "idle",
  listening: "listening",
  thinking: "thinking",
  speaking: "speaking",
  minimized: "idle",
  notification: "searching",
};

interface Msg {
  id: number;
  role: "user" | "assistant";
  text: string;
}

const DEMO_REPLIES = [
  "SMM agent kanal statistikasini yig'di: oxirgi hafta +340 a'zo, eng yaxshi post — seshanba kungi video.",
  "Bugungi jadval: 3 vazifa kutmoqda, 08:00 briefing tayyorlandi. Birinchisidan boshlaymi?",
  "Developer agent PR #42'ni ko'rib chiqdi — 2 ta izoh qoldirdi, CI yashil.",
];

/* Selektor pill — model/kontekst/tool ko'rsatkichi (hozircha statik) */
function SelectorPill({ label, value }: { label: string; value: string }) {
  return (
    <button className="flex items-center gap-1.5 rounded-full border border-[var(--border-hairline)] bg-[var(--bg-elevated)] px-3.5 py-1.5 text-xs text-[var(--text-secondary)] transition-colors hover:border-[var(--border-active)] hover:text-[var(--text-primary)]">
      <span className="text-[var(--text-muted)]">{label}:</span>
      <span className="text-[var(--text-primary)]">{value}</span>
      <ChevronDown size={13} strokeWidth={1.5} className="text-[var(--text-muted)]" />
    </button>
  );
}

export default function AiChatPage() {
  const { state, send } = useAssistant("listening");
  const [messages, setMessages] = useState<Msg[]>([
    { id: 1, role: "assistant", text: "Salom! Buyruq bering — matn yoki ovoz bilan." },
  ]);
  const [input, setInput] = useState("");
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const nextId = useRef(2);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, state]);

  const submit = useCallback(() => {
    const text = input.trim();
    if (!text || state === "thinking") return;
    if (state === "sleep") send("WAKE");

    setMessages((m) => [...m, { id: nextId.current++, role: "user", text }]);
    setInput("");
    send("SUBMIT");

    const reply = DEMO_REPLIES[Math.floor(Math.random() * DEMO_REPLIES.length)];
    timers.current.push(
      setTimeout(() => {
        send("RESPOND");
        const msgId = nextId.current++;
        setMessages((m) => [...m, { id: msgId, role: "assistant", text: "" }]);
        let i = 0;
        const typer = setInterval(() => {
          i += 2;
          setMessages((m) =>
            m.map((msg) => (msg.id === msgId ? { ...msg, text: reply.slice(0, i) } : msg)),
          );
          if (i >= reply.length) {
            clearInterval(typer);
            timers.current.push(setTimeout(() => send("DONE"), 500));
          }
        }, 24);
      }, 2400),
    );
  }, [input, state, send]);

  const voiceActive = state === "listening" || state === "speaking";

  return (
    <div className="mx-auto flex h-[calc(100vh-8.5rem)] max-w-3xl flex-col px-6 py-4">
      {/* Model/kontekst selektorlar */}
      <div className="flex flex-wrap items-center justify-center gap-2">
        <SelectorPill label="Model" value="T1 · Gemini Flash" />
        <SelectorPill label="Xotira" value="To'liq" />
        <SelectorPill label="Tool" value="24 ta" />
      </div>

      {/* Orb + waveform */}
      <div className="flex flex-col items-center">
        <button
          aria-label="ZET holati"
          className="relative h-[260px] w-[260px] cursor-pointer outline-none"
          onClick={() => {
            if (state === "sleep") send("WAKE");
          }}
        >
          <NeuroOrb state={TO_ORB[state]} className="absolute inset-0" />
        </button>
        <Waveform active={voiceActive} width={300} height={40} className="-mt-3" />
      </div>

      {/* Chat oqimi */}
      <div ref={scrollRef} className="mt-2 flex-1 space-y-3 overflow-y-auto py-3 pr-1">
        <AnimatePresence initial={false}>
          {messages.map((m) => (
            <motion.div
              key={m.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, ease: "easeOut" }}
              className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[80%] rounded-[14px] px-4 py-2.5 text-sm leading-relaxed ${
                  m.role === "user"
                    ? "border border-[var(--border-active)] bg-[rgba(76,141,255,0.08)] text-[var(--text-primary)]"
                    : "border border-[var(--border-hairline)] bg-[var(--bg-elevated)] text-[var(--text-primary)]"
                }`}
              >
                {m.text || (
                  <span className="pulse-dot inline-block h-3.5 w-[2px] bg-[var(--accent-glow)] align-middle" />
                )}
              </div>
            </motion.div>
          ))}
          {state === "thinking" ? (
            <motion.div
              key="chip"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="flex justify-start"
            >
              <AgentStatusChip kind="thinking" />
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>

      {/* Input */}
      <CommandInput
        value={input}
        onChange={setInput}
        onSubmit={submit}
        disabled={state === "thinking"}
        onMic={() => {
          if (state === "sleep") send("WAKE");
        }}
      />
    </div>
  );
}
