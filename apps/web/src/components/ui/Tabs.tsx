"use client";

/** Pill tab guruhi — devices/camera/terminal sahifalarida bir xil UI edi,
 * endi bitta komponent (CLAUDE.md sifat standarti: dublikat yo'q).
 * A11y: role=tablist/tab, aria-selected, strelka bilan almashish.
 */

import { useRef } from "react";

import { sound } from "@/lib/sound";

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  labels,
}: {
  tabs: readonly T[];
  value: T;
  onChange: (t: T) => void;
  /** Ixtiyoriy ko'rinadigan matn (id → yorliq); berilmasa id o'zi */
  labels?: Partial<Record<T, string>>;
}) {
  const refs = useRef<Map<T, HTMLButtonElement>>(new Map());

  const move = (dir: -1 | 1) => {
    const i = tabs.indexOf(value);
    const next = tabs[(i + dir + tabs.length) % tabs.length];
    onChange(next);
    refs.current.get(next)?.focus();
  };

  return (
    <div
      role="tablist"
      className="flex gap-1 rounded-full border border-[var(--border-hairline)] bg-[var(--bg-elevated)] p-1"
    >
      {tabs.map((t) => {
        const active = t === value;
        return (
          <button
            key={t}
            ref={(el) => {
              if (el) refs.current.set(t, el);
            }}
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onKeyDown={(e) => {
              if (e.key === "ArrowRight") move(1);
              if (e.key === "ArrowLeft") move(-1);
            }}
            onClick={() => {
              sound.play("tick");
              onChange(t);
            }}
            className={`rounded-full px-3.5 py-1 text-xs transition-colors ${
              active
                ? "bg-[var(--accent-blue)] text-[#050608]"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            }`}
          >
            {labels?.[t] ?? t}
          </button>
        );
      })}
    </div>
  );
}
