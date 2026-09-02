"use client";

/** Ma'lumot kartalari v2 — Panel uslubi (hairline, blur yo'q).
 * StatCard · AgentListItem · ProgressRing · RadialGauge · Sparkline
 */

import { motion } from "motion/react";

import { Eyebrow, Panel, StatusDot } from "@/components/ui/primitives";

/* ── StatCard ─────────────────────────────────────────────────── */

export function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <Panel className="px-5 py-4">
      <Eyebrow>{label}</Eyebrow>
      <div className="data mt-1.5 text-3xl font-semibold text-[var(--text-primary)]">{value}</div>
      {hint ? <div className="mt-1 text-xs text-[var(--text-secondary)]">{hint}</div> : null}
    </Panel>
  );
}

/* ── Agent statuslari ─────────────────────────────────────────── */

export type AgentStatus = "online" | "working" | "thinking" | "offline" | "paused";

const AGENT_STATUS: Record<AgentStatus, { color: string; label: string; pulse: boolean }> = {
  online: { color: "var(--status-online)", label: "Onlayn", pulse: false },
  working: { color: "var(--status-working)", label: "Ishlayapti", pulse: true },
  // thinking working bilan bir rang — faqat pulse tezligi farqli (master tizim)
  thinking: { color: "var(--status-thinking)", label: "O'ylayapti", pulse: true },
  offline: { color: "var(--status-offline)", label: "Oflayn", pulse: false },
  paused: { color: "var(--status-offline)", label: "To'xtatilgan", pulse: false },
};

export function AgentListItem({
  name,
  division,
  status,
}: {
  name: string;
  division: string;
  status: AgentStatus;
}) {
  const s = AGENT_STATUS[status];
  return (
    <div className="flex items-center gap-3 rounded-[10px] px-3 py-2.5 transition-colors hover:bg-[var(--surface-hover)]">
      <div className="flex h-8 w-8 items-center justify-center rounded-full border border-[var(--border-hairline)] bg-[var(--bg-base)]">
        <span className="data text-[10px] font-medium text-[var(--accent-blue)]">
          {name.slice(0, 2).toUpperCase()}
        </span>
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm text-[var(--text-primary)]">{name}</div>
        <div className="truncate text-xs text-[var(--text-muted)]">{division}</div>
      </div>
      <div className="flex items-center gap-2">
        <StatusDot color={s.color} pulse={s.pulse} />
        <span className="text-xs" style={{ color: s.color }}>
          {s.label}
        </span>
      </div>
    </div>
  );
}

/* ── ProgressRing (katta, markazda %) ─────────────────────────── */

export function ProgressRing({
  percent,
  size = 96,
  label,
}: {
  percent: number;
  size?: number;
  label?: string;
}) {
  const r = (size - 10) / 2;
  const C = 2 * Math.PI * r;
  const clamped = Math.max(0, Math.min(100, percent));
  return (
    <div
      className="relative inline-flex items-center justify-center"
      style={{ width: size, height: size }}
    >
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--border-hairline)"
          strokeWidth="4"
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--accent-blue)"
          strokeWidth="4"
          strokeLinecap="round"
          strokeDasharray={C}
          initial={{ strokeDashoffset: C }}
          animate={{ strokeDashoffset: C - (C * clamped) / 100 }}
          transition={{ duration: 0.9, ease: "easeOut" }}
        />
      </svg>
      <div className="absolute text-center">
        <div className="data text-xl font-semibold text-[var(--text-primary)]">{clamped}%</div>
        {label ? <div className="text-[10px] text-[var(--text-muted)]">{label}</div> : null}
      </div>
    </div>
  );
}

/* ── RadialGauge (kichik — System Status metrikasi) ───────────── */

export function RadialGauge({
  percent,
  label,
  value,
}: {
  percent: number;
  label: string;
  value: string;
}) {
  const size = 54;
  const r = 23;
  const C = 2 * Math.PI * r;
  const clamped = Math.max(0, Math.min(100, percent));
  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90">
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke="var(--border-hairline)"
            strokeWidth="3"
          />
          <motion.circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke="var(--accent-blue)"
            strokeWidth="3"
            strokeLinecap="round"
            strokeDasharray={C}
            initial={{ strokeDashoffset: C }}
            animate={{ strokeDashoffset: C - (C * clamped) / 100 }}
            transition={{ duration: 0.8, ease: "easeOut" }}
          />
        </svg>
        <div className="data absolute inset-0 flex items-center justify-center text-[11px] text-[var(--text-primary)]">
          {value}
        </div>
      </div>
      <span className="eyebrow !text-[9px]">{label}</span>
    </div>
  );
}

/* ── Sparkline ────────────────────────────────────────────────── */

export function Sparkline({
  data,
  width = 120,
  height = 32,
  id = "spark",
}: {
  data: number[];
  width?: number;
  height?: number;
  id?: string;
}) {
  if (data.length < 2) return null;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const pts = data
    .map(
      (v, i) =>
        `${(i / (data.length - 1)) * width},${height - 3 - ((v - min) / range) * (height - 6)}`,
    )
    .join(" ");
  const last = data[data.length - 1];
  const lastY = height - 3 - ((last - min) / range) * (height - 6);
  return (
    <svg width={width} height={height} className="overflow-visible">
      <defs>
        <linearGradient id={`${id}-fill`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent-blue)" />
          <stop offset="100%" stopColor="transparent" />
        </linearGradient>
      </defs>
      <polygon points={`0,${height} ${pts} ${width},${height}`} fill={`url(#${id}-fill)`} opacity="0.18" />
      <polyline
        points={pts}
        fill="none"
        stroke="var(--accent-blue)"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <circle cx={width} cy={lastY} r="2.5" fill="var(--accent-glow)" />
    </svg>
  );
}
