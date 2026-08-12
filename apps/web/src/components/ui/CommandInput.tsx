"use client";

/** Buyruq kiritish paneli — input + mikrofon + yuborish.
 * AssistantHero, /ai-chat va /tg da BIR XIL UI uch marta yozilgan edi —
 * endi bitta komponent (sifat standarti: dublikat yo'q).
 */

import { Mic, SendHorizontal } from "lucide-react";
import { motion } from "motion/react";

import { sound } from "@/lib/sound";

export function CommandInput({
  value,
  onChange,
  onSubmit,
  onMic,
  disabled = false,
  placeholder = "Buyruq yozing yoki ovoz bilan gapiring…",
  onFocus,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onMic?: () => void;
  disabled?: boolean;
  placeholder?: string;
  onFocus?: () => void;
}) {
  return (
    <div className="flex w-full items-center gap-2 rounded-full border border-[var(--border-hairline)] bg-[var(--bg-elevated)] py-1.5 pl-5 pr-1.5 transition-colors focus-within:border-[var(--border-active)]">
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={onFocus}
        onKeyDown={(e) => {
          if (e.key === "Enter") onSubmit();
        }}
        aria-label="Buyruq"
        placeholder={placeholder}
        className="w-full bg-transparent text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)]"
      />
      {onMic ? (
        <button
          aria-label="Ovozli buyruq"
          className="rounded-full p-2.5 text-[var(--text-secondary)] transition-colors hover:text-[var(--accent-blue)]"
          onClick={() => {
            sound.play("listenStart");
            onMic();
          }}
        >
          <Mic size={18} strokeWidth={1.5} />
        </button>
      ) : null}
      <motion.button
        aria-label="Yuborish"
        whileTap={{ scale: 0.95 }}
        transition={{ type: "spring", stiffness: 300, damping: 30 }}
        className="rounded-full bg-[var(--accent-blue)] p-2.5 text-[#050608] transition-[filter] hover:brightness-110 disabled:opacity-40"
        disabled={!value.trim() || disabled}
        onClick={onSubmit}
      >
        <SendHorizontal size={18} strokeWidth={1.5} />
      </motion.button>
    </div>
  );
}
