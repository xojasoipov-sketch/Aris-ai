"use client";

/** Assistant hero v2 — markazda <NeuroOrb /> (CLAUDE.md master tizim).
 *
 * Holat mashinasi (lib/assistant-machine) orb holatiga map qilinadi;
 * har o'tish tovush bilan sinxron. Demo javob sikli — real orchestrator
 * SSE keyingi fazada ulanadi.
 */

import { Mic, SendHorizontal } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";

import { NeuroOrb, type OrbState } from "@/components/core/NeuroOrb";
import { AgentStatusChip } from "@/components/ui/AgentStatusChip";
import {
  STATE_LABEL,
  useAssistant,
  type AssistantState,
} from "@/lib/assistant-machine";
import { sound } from "@/lib/sound";

/* Mashina holati → orb holati */
const TO_ORB: Record<AssistantState, OrbState> = {
  sleep: "idle",
  listening: "listening",
  thinking: "thinking",
  speaking: "speaking",
  minimized: "idle",
  notification: "searching",
};

const DEMO_REPLY =
  "Tushundim. SMM agent bugungi kanal statistikasini yig'yapti — tayyor bo'lganda xabar beraman.";

export function AssistantHero() {
  const { state, send } = useAssistant("sleep");
  const [input, setInput] = useState("");
  const [reply, setReply] = useState("");
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  const submit = useCallback(() => {
    if (!input.trim() || state === "thinking") return;
    if (state === "sleep" || state === "minimized") send("WAKE");
    setReply("");
    send("SUBMIT");
    timers.current.push(
      setTimeout(() => {
        send("RESPOND");
        let i = 0;
        const typeTimer = setInterval(() => {
          i += 2;
          setReply(DEMO_REPLY.slice(0, i));
          if (i >= DEMO_REPLY.length) {
            clearInterval(typeTimer);
            timers.current.push(setTimeout(() => send("DONE"), 600));
          }
        }, 28);
      }, 2600),
    );
    setInput("");
  }, [input, state, send]);

  return (
    <div className="relative flex flex-col items-center">
      {/* Orb — 440px (spec: 400–500px), bosilganda uyg'onadi */}
      <button
        aria-label={state === "sleep" ? "ZET'ni uyg'otish" : "ZET holati"}
        className="relative h-[440px] w-[440px] cursor-pointer outline-none"
        onClick={() => {
          if (state === "sleep" || state === "minimized") send("WAKE");
          else if (state === "listening") send("CANCEL");
        }}
      >
        <NeuroOrb state={TO_ORB[state]} className="absolute inset-0" />
      </button>

      {/* Holat matni / javob / chip */}
      <div className="flex min-h-[64px] w-full max-w-lg flex-col items-center gap-3 text-center">
        <AnimatePresence mode="wait">
          {state === "thinking" ? (
            <AgentStatusChip key="chip" kind="thinking" />
          ) : reply && (state === "speaking" || state === "listening") ? (
            <motion.p
              key="reply"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3, ease: "easeOut" }}
              className="text-sm leading-relaxed text-[var(--text-primary)]"
            >
              {reply}
              {state === "speaking" ? (
                <span className="pulse-dot ml-0.5 inline-block h-4 w-[2px] bg-[var(--accent-glow)] align-middle" />
              ) : null}
            </motion.p>
          ) : (
            <motion.p
              key={`label-${state}`}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3, ease: "easeOut" }}
              className="text-sm text-[var(--text-secondary)]"
            >
              {STATE_LABEL[state]}
            </motion.p>
          )}
        </AnimatePresence>
      </div>

      {/* Buyruq paneli */}
      <div className="mt-2 flex w-full max-w-lg items-center gap-2 rounded-full border border-[var(--border-hairline)] bg-[var(--bg-elevated)] py-1.5 pl-5 pr-1.5">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onFocus={() => {
            if (state === "sleep") send("WAKE");
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
          placeholder="Buyruq yozing yoki ovoz bilan gapiring…"
          className="w-full bg-transparent text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)]"
        />
        <button
          aria-label="Ovozli buyruq"
          className="rounded-full p-2.5 text-[var(--text-secondary)] transition-colors hover:text-[var(--accent-blue)]"
          onClick={() => {
            sound.play("listenStart");
            if (state === "sleep") send("WAKE");
          }}
        >
          <Mic size={18} strokeWidth={1.5} />
        </button>
        <motion.button
          aria-label="Yuborish"
          whileTap={{ scale: 0.95 }}
          transition={{ type: "spring", stiffness: 300, damping: 30 }}
          className="rounded-full bg-[var(--accent-blue)] p-2.5 text-[#050608] transition-[filter] hover:brightness-110 disabled:opacity-40"
          disabled={!input.trim() || state === "thinking"}
          onClick={submit}
        >
          <SendHorizontal size={18} strokeWidth={1.5} />
        </motion.button>
      </div>
    </div>
  );
}
