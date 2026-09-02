"use client";

/** Forma primitivlari — Toggle, SettingsRow, EmptyState.
 * Settings sahifasidan umumiy foydalanishga ko'chirildi (dublikat yo'q).
 */

import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { sound } from "@/lib/sound";

export function Toggle({
  on,
  onChange,
  label,
}: {
  on: boolean;
  onChange: (v: boolean) => void;
  label?: string;
}) {
  return (
    <button
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={() => {
        sound.play("tick");
        onChange(!on);
      }}
      className={`relative h-5.5 w-10 rounded-full transition-colors ${
        on
          ? "bg-[var(--status-online)]"
          : "border border-[var(--border-hairline)] bg-[var(--surface-hover)]"
      }`}
    >
      <span
        className={`absolute top-0.5 h-4.5 w-4.5 rounded-full bg-[var(--text-primary)] transition-[left] duration-200 ${
          on ? "left-5" : "left-0.5"
        }`}
      />
    </button>
  );
}

/** Sozlamalar qatori — chap yorliq, o'ng qiymat/boshqaruv. */
export function SettingsRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-[var(--border-hairline)] py-3 last:border-0">
      <span className="text-sm text-[var(--text-primary)]">{label}</span>
      {children}
    </div>
  );
}

/** Bo'sh/uzilgan holat — halol production holati (soxta ma'lumot o'rniga). */
export function EmptyState({
  icon: Icon,
  title,
  hint,
  action,
}: {
  icon?: LucideIcon;
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 py-10 text-center">
      {Icon ? (
        <Icon size={22} strokeWidth={1.5} className="text-[var(--text-muted)]" aria-hidden />
      ) : null}
      <p className="text-sm text-[var(--text-secondary)]">{title}</p>
      {hint ? <p className="max-w-xs text-xs text-[var(--text-muted)]">{hint}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
