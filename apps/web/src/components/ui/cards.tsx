"use client";

/** Ma'lumot kartalari — docs/10 §3.4.
 * StatCard · AgentListItem · ProgressRing · Sparkline
 */

import { motion } from "framer-motion";

import { GlassPanel, StatusDot, TechLabel } from "@/components/ui/primitives";

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
    <GlassPanel className="px-5 py-4">
      <TechLabel>{label}</TechLabel>
      <div className="tabular mt-1.5 text-3xl font-bold text-[var(--text-primary)]">
        {value}
      </div>
      {hint ? (
        <div className="mt-1 text-xs text-[var(--text-secondary)]">{hint}</div>
      ) : null}
    </GlassPanel>
  );
}

/* ── Agent statuslari ─────────────────────────────────────────── */

export type AgentStatus = "online" | "working" | "thinking" | "offline" | "paused";

const AGENT_STATUS: Record<AgentStatus, { color: string; label: string; pulse: boolean }> = {
  online: { color: "var(--state-online)", label: "Onlayn", pulse: false },
  working: { color: "var(--state-working)", label: "Ishlayapti", pulse: true },
  thinking: { color: "var(--state-thinking)", label: "O'ylayapti", pulse: true },
  offline: { color: "var(--state-offline)", label: "Oflayn", pulse: false },
  paused: { color: "var(--state-offline)", label: "To'xtatilgan", pulse: false },
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
    <div className="flex items-center gap-3 rounded-[12px] px-3 py-2.5 transition-colors hover:bg-[var(--bg-elevated)]">
      {/* Avatar — zarrachali mini-doira */}
      <div
        className="flex h-8 w-8 items-center justify-center rounded-full border border-[var(--border-subtle)]"
        style={{ background: "radial-gradient(circle at 40% 35%, rgba(56,189,248,0.25), transparent 70%)" }}
      >
        <span className="font-mono text-[10px] font-semibold text-[var(--accent-cyan)]">
          {name.slice(0, 2).toUpperCase()}
        </span>
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-[var(--text-primary)]">{name}</div>
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

/* ── ProgressRing ─────────────────────────────────────────────── */

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
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--border-subtle)"
          strokeWidth="5"
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--accent-primary)"
          strokeWidth="5"
          strokeLinecap="round"
          strokeDasharray={C}
          initial={{ strokeDashoffset: C }}
          animate={{ strokeDashoffset: C - (C * clamped) / 100 }}
          transition={{ duration: 1, ease: "easeOut" }}
          style={{ filter: "drop-shadow(0 0 6px var(--accent-glow))" }}
        />
      </svg>
      <div className="absolute text-center">
        <div className="tabular text-xl font-bold text-[var(--text-primary)]">{clamped}%</div>
        {label ? <div className="text-[10px] text-[var(--text-muted)]">{label}</div> : null}
      </div>
    </div>
  );
}

/* ── Sparkline — mini grafik (SYSTEM STATUS kartasi uchun) ────── */

export function Sparkline({
  data,
  width = 120,
  height = 32,
}: {
  data: number[];
  width?: number;
  height?: number;
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
      <polyline
        points={pts}
        fill="none"
        stroke="var(--accent-primary)"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <polygon
        points={`0,${height} ${pts} ${width},${height}`}
        fill="url(#spark-fill)"
        opacity="0.25"
      />
      <defs>
        <linearGradient id="spark-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent-primary)" />
          <stop offset="100%" stopColor="transparent" />
        </linearGradient>
      </defs>
      {/* Oxirgi nuqta ta'kidlangan */}
      <circle cx={width} cy={lastY} r="2.5" fill="var(--accent-cyan)" />
    </svg>
  );
}
