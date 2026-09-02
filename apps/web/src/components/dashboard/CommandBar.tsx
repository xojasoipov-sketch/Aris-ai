"use client";

/** Buyruq paneli — dashboard'ning ish quroli (Z46.2).
 *
 * ILGARI NIMA BO'LGAN. Dashboard'ning bosh ish quroli SOXTA edi:
 *
 *     const DEMO_REPLY = "SMM agent kanal statistikasini yig'yapti…";
 *
 * Har qanday buyruqqa 2200 ms "o'ylash" pauzasidan keyin AYNAN shu
 * bitta jumla harfma-harf yozilardi. Backend'ga hech narsa bormasdi.
 *
 * Endi `POST /run` orqali haqiqiy buyruq yuboriladi va ZET'ning
 * haqiqiy javobi ko'rsatiladi. Xato bo'lsa — xato ochiq aytiladi,
 * jimgina soxta javob emas.
 */

import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";

import { NeuroOrb, type OrbState } from "@/components/core/NeuroOrb";
import { api } from "@/lib/api";
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

export function CommandBar() {
  const { state, send } = useAssistant("sleep");
  const [input, setInput] = useState("");
  const [reply, setReply] = useState("");
  const [failed, setFailed] = useState(false);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    const pending = timers.current;
    return () => {
      aliveRef.current = false;
      pending.forEach(clearTimeout);
    };
  }, []);

  const submit = useCallback(() => {
    const message = input.trim();
    if (!message || state === "thinking") return;
    if (state === "sleep" || state === "minimized") send("WAKE");
    setReply("");
    setFailed(false);
    send("SUBMIT");
    setInput("");

    void (async () => {
      const res = await api.run(message);
      // Javob kelguncha komponent yopilgan bo'lishi mumkin.
      if (!aliveRef.current) return;

      send("RESPOND");
      if (res.ok) {
        setReply(res.data.message || "(bo'sh javob)");
      } else {
        // Xatoni SOXTA javob bilan yashirmaymiz — ega nima
        // bo'lganini bilishi kerak.
        setFailed(true);
        setReply(res.error);
      }
      timers.current.push(setTimeout(() => send("DONE"), 400));
    })();
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
            <p
              className={`mt-3 border-t border-[var(--border-hairline)] pt-3 text-sm leading-relaxed ${
                failed ? "text-[var(--status-alert)]" : "text-[var(--text-primary)]"
              }`}
            >
              {reply}
            </p>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </Panel>
  );
}
