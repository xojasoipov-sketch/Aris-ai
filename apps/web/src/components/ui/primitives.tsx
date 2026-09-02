"use client";

/** ZET UI primitivlari v2 — CLAUDE.md master tizim.
 * Panel: hairline chegara + inset highlight, blur YO'Q (blur faqat .floating).
 */

import { motion } from "motion/react";
import type { ComponentProps, ReactNode } from "react";

import { sound } from "@/lib/sound";

/** Asosiy karta — .panel (globals.css). */
export function Panel({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`panel ${className}`}>{children}</div>;
}

/** Eyebrow yorliq — "SYSTEM STATUS" uslubi. */
export function Eyebrow({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`eyebrow ${className}`}>{children}</div>;
}

type ButtonVariant = "primary" | "ghost" | "danger";

const BUTTON_STYLES: Record<ButtonVariant, string> = {
  primary: "bg-[var(--accent-blue)] text-[#050608] font-medium hover:brightness-110",
  ghost:
    "bg-transparent border border-[var(--border-hairline)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-active)]",
  danger:
    "bg-transparent border border-[var(--status-alert)] text-[var(--status-alert)] hover:bg-[var(--status-alert)] hover:text-[#050608] font-medium",
};

/** Tugma — spring(300,30), bounce yo'q; bosilganda tick tovushi. */
export function Button({
  variant = "ghost",
  className = "",
  onClick,
  children,
  ...rest
}: ComponentProps<"button"> & { variant?: ButtonVariant }) {
  return (
    <motion.button
      whileTap={{ scale: 0.98 }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
      className={`rounded-[10px] px-4 py-2 text-sm transition-colors duration-150 disabled:opacity-40 disabled:pointer-events-none ${BUTTON_STYLES[variant]} ${className}`}
      onClick={(e) => {
        sound.play("tick");
        onClick?.(e as never);
      }}
      {...(rest as object)}
    >
      {children}
    </motion.button>
  );
}

/** Holat nuqtasi — semantik token rangi. */
export function StatusDot({ color, pulse = false }: { color: string; pulse?: boolean }) {
  return (
    <span
      className={`inline-block h-1.5 w-1.5 rounded-full ${pulse ? "pulse-dot" : ""}`}
      style={{ background: color }}
    />
  );
}
