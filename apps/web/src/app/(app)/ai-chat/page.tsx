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

import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Waveform } from "@/components/assistant/Waveform";
import { NeuroOrb, type OrbState } from "@/components/core/NeuroOrb";
import { api } from "@/lib/api";
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

/* Selektor pill — model/kontekst/tool ko'rsatkichi (hozircha statik) */
export default function AiChatPage() {
  const { state, send } = useAssistant("listening");
  const [messages, setMessages] = useState<Msg[]>([
    { id: 1, role: "assistant", text: "Salom! Buyruq bering — matn yoki ovoz bilan." },
  ]);
  const [input, setInput] = useState("");
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const nextId = useRef(2);

  const aliveRef = useRef(true);
  useEffect(() => {
    aliveRef.current = true;
    const pending = timers.current;
    return () => {
      aliveRef.current = false;
      pending.forEach(clearTimeout);
    };
  }, []);
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

    void (async () => {
      const res = await api.run(text);
      if (!aliveRef.current) return;

      send("RESPOND");
      setMessages((m) => [
        ...m,
        {
          id: nextId.current++,
          role: "assistant",
          // Xato SOXTA javob bilan yashirilmaydi.
          text: res.ok ? res.data.message || "(bo'sh javob)" : `Xato: ${res.error}`,
        },
      ]);
      timers.current.push(setTimeout(() => send("DONE"), 400));
    })();
  }, [input, state, send]);

  const voiceActive = state === "listening" || state === "speaking";

  return (
    <div className="mx-auto flex h-[calc(100vh-8.5rem)] max-w-3xl flex-col px-6 py-4">
      {/* Orb + waveform */}
      <div className="flex flex-col items-center">
        <button
          aria-label="ZET holati"
          className="relative h-[150px] w-[150px] cursor-pointer outline-none"
          onClick={() => {
            if (state === "sleep") send("WAKE");
          }}
        >
          <NeuroOrb state={TO_ORB[state]} className="absolute inset-0" />
        </button>
        <Waveform active={voiceActive} width={240} height={32} className="-mt-1" />
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
