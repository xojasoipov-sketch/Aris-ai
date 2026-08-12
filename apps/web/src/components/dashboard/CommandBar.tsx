"use client";

/** Buyruq paneli — dashboard'ning ish quroli (sifat standarti: orb endi
 * qahramon emas, 44px status-indikator; asosiy element — input).
 *
 * Holat mashinasi + tovushlar saqlanadi; javob pastda oddiy matn bloki
 * sifatida chiqadi (kontsept-art markaziy sahna YO'Q).
 */

import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";

import { NeuroOrb, type OrbState } from "@/components/core/NeuroOrb";
import { CommandInput } from "@/components/ui/CommandInput";
import { Panel } from "@/components/ui/primitives";
import {
  STATE_LABEL,
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

const DEMO_REPLY =
  "SMM agent kanal statistikasini yig'yapti — tayyor bo'lganda xabar beraman.";

export function CommandBar() {
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
        const typer = setInterval(() => {
          i += 2;
          setReply(DEMO_REPLY.slice(0, i));
          if (i >= DEMO_REPLY.length) {
            clearInterval(typer);
            timers.current.push(setTimeout(() => send("DONE"), 500));
          }
        }, 22);
      }, 2200),
    );
    setInput("");
  }, [input, state, send]);

  return (
    <Panel className="p-3">
      <div className="flex items-center gap-3">
        {/* Orb — kichik holat-indikator (bosilsa uyg'onadi/tinchiydi) */}
        <button
          aria-label={STATE_LABEL[state]}
          title={STATE_LABEL[state]}
          onClick={() => {
            if (state === "sleep") send("WAKE");
            else if (state === "listening") send("CANCEL");
          }}
          className="h-11 w-11 shrink-0 rounded-full border border-[var(--border-hairline)] outline-none transition-colors hover:border-[var(--border-active)]"
        >
          <NeuroOrb state={TO_ORB[state]} mini seedOffset={0} className="h-full w-full" />
        </button>

        <div className="min-w-0 flex-1">
          <CommandInput
            value={input}
            onChange={setInput}
            onSubmit={submit}
            disabled={state === "thinking"}
            onFocus={() => {
              if (state === "sleep") send("WAKE");
            }}
            onMic={() => {
              if (state === "sleep") send("WAKE");
            }}
          />
        </div>

        {/* Holat matni — inline, faqat faol jarayonda */}
        <AnimatePresence>
          {state !== "sleep" ? (
            <motion.span
              key={state}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="hidden shrink-0 text-xs text-[var(--text-muted)] md:block"
            >
              {STATE_LABEL[state]}
            </motion.span>
          ) : null}
        </AnimatePresence>
      </div>

      {/* Javob — oddiy matn bloki */}
      <AnimatePresence>
        {reply ? (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.25, ease: "easeOut" }}
            className="overflow-hidden"
          >
            <p className="mt-3 border-t border-[var(--border-hairline)] pt-3 text-sm leading-relaxed text-[var(--text-primary)]">
              {reply}
              {state === "speaking" ? (
                <span className="pulse-dot ml-0.5 inline-block h-3.5 w-[2px] bg-[var(--accent-blue)] align-middle" />
              ) : null}
            </p>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </Panel>
  );
}
