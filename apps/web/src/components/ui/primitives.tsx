"use client";

/** ZET UI primitivlari — glass panel, tugma, texnik yorliq.
 * ADR-0005 token'laridan boshqa rang YO'Q.
 */

import { motion } from "framer-motion";
import type { ComponentProps, ReactNode } from "react";

import { sound } from "@/lib/sound";

/** Glass panel — docs/10 §1 (rgba fon + blur + nozik chegara). */
export function GlassPanel({
  children,
  className = "",
  glow = false,
}: {
  children: ReactNode;
  className?: string;
  glow?: boolean;
}) {
  return (
    <div
      className={`glass rounded-[16px] ${glow ? "border-[var(--border-glow)]" : ""} ${className}`}
    >
      {children}
    </div>
  );
}

/** Texnik yorliq — UPPERCASE mono (mockup: "SYSTEM STATUS"). */
export function TechLabel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`tech-label ${className}`}>{children}</div>;
}

type ButtonVariant = "primary" | "ghost" | "danger";

const BUTTON_STYLES: Record<ButtonVariant, string> = {
  primary:
    "bg-[var(--accent-primary)] text-[#05070D] font-semibold hover:brightness-110",
  ghost:
    "bg-transparent border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-glow)]",
  danger:
    "bg-transparent border border-[var(--state-danger)] text-[var(--state-danger)] hover:bg-[var(--state-danger)] hover:text-[#05070D] font-semibold",
};

/** Tugma — bosilganda "tick" tovushi (har bir buyruq his qilinadi). */
export function Button({
  variant = "ghost",
  className = "",
  onClick,
  children,
  ...rest
}: ComponentProps<"button"> & { variant?: ButtonVariant }) {
  return (
    <motion.button
      whileTap={{ scale: 0.97 }}
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

/** Holat nuqtasi — rang semantik token'dan. */
export function StatusDot({
  color,
  pulse = false,
}: {
  color: string;
  pulse?: boolean;
}) {
  return (
    <span
      className={`inline-block h-2 w-2 rounded-full ${pulse ? "animate-pulse-dot" : ""}`}
      style={{ background: color, boxShadow: `0 0 8px ${color}` }}
    />
  );
}
