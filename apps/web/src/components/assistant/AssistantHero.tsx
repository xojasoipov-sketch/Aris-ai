"use client";

/** Assistant hero — dashboard markazi: zarrachali yadro + holat + buyruq paneli.
 *
 * To'liq sikl (docs/10 §3.2): sleep → (tap/yozish) → listening → SUBMIT →
 * thinking → RESPOND → speaking → DONE → listening. Har o'tish tovush va
 * zarracha harakati bilan sinxron — "buyruq his qilinadi".
 *
 * Hozircha orchestrator demo rejimda (backend /run endpoint'i Bo'lim 10
 * doirasidan tashqarida) — lekin butun holat oqimi real.
 */

import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";

import { ParticleCore } from "@/components/core/ParticleCore";
import { IconMic, IconSend } from "@/components/ui/icons";
import { StatusPill } from "@/components/ui/StatusPill";
import { STATE_LABEL, useAssistant } from "@/lib/assistant-machine";
import { sound } from "@/lib/sound";

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
    // Demo javob sikli — keyin real orchestrator SSE bilan almashadi
    timers.current.push(
      setTimeout(() => {
        send("RESPOND");
        // Harf-baharf yozish effekti
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
      {/* Yadro — bosilganda uyg'onadi/uxlaydi */}
      <button
        aria-label={state === "sleep" ? "ZET'ni uyg'otish" : "ZET holati"}
        className="relative h-[340px] w-[340px] cursor-pointer outline-none"
        onClick={() => {
          if (state === "sleep" || state === "minimized") send("WAKE");
          else if (state === "listening") send("CANCEL");
        }}
      >
        {/* Orqa halo — holatga qarab kuchayadi */}
        <motion.div
          aria-hidden
          className="absolute inset-6 rounded-full"
          animate={{
            boxShadow:
              state === "sleep"
                ? "0 0 60px 0 rgba(56,189,248,0.12)"
                : state === "thinking"
                  ? "0 0 140px 24px rgba(56,189,248,0.28)"
                  : "0 0 100px 12px rgba(56,189,248,0.2)",
          }}
          transition={{ duration: 1.2 }}
        />
        <ParticleCore state={state} className="absolute inset-0" />
      </button>

      {/* Holat matni / javob */}
      <div className="flex min-h-[72px] w-full max-w-lg flex-col items-center gap-3 text-center">
        <AnimatePresence mode="wait">
          {state === "thinking" ? (
            <StatusPill key="pill" kind="thinking" />
          ) : reply && (state === "speaking" || state === "listening") ? (
            <motion.p
              key="reply"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="text-sm leading-relaxed text-[var(--text-primary)]"
            >
              {reply}
              {state === "speaking" ? (
                <span className="ml-0.5 inline-block h-4 w-[2px] animate-pulse-dot bg-[var(--accent-cyan)] align-middle" />
              ) : null}
            </motion.p>
          ) : (
            <motion.p
              key={`label-${state}`}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="text-sm text-[var(--text-secondary)]"
            >
              {STATE_LABEL[state]}
            </motion.p>
          )}
        </AnimatePresence>
      </div>

      {/* Buyruq paneli */}
      <div className="glass mt-2 flex w-full max-w-lg items-center gap-2 rounded-full py-1.5 pl-5 pr-1.5">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onFocus={() => {
            if (state === "sleep") send("WAKE");
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
          placeholder="Buyruq yozing yoki ovoz bilan gapiring..."
          className="w-full bg-transparent text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)]"
        />
        <button
          aria-label="Ovozli buyruq"
          className="rounded-full p-2.5 text-[var(--text-secondary)] transition-colors hover:text-[var(--accent-cyan)]"
          onClick={() => {
            sound.play("listenStart");
            if (state === "sleep") send("WAKE");
          }}
        >
          <IconMic />
        </button>
        <motion.button
          aria-label="Yuborish"
          whileTap={{ scale: 0.92 }}
          className="rounded-full bg-[var(--accent-primary)] p-2.5 text-[#05070D] transition-[filter] hover:brightness-110 disabled:opacity-40"
          disabled={!input.trim() || state === "thinking"}
          onClick={submit}
        >
          <IconSend />
        </motion.button>
      </div>
    </div>
  );
}
