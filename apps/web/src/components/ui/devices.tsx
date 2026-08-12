"use client";

/** Devices sahifasi komponentlari v2 — docs/11 §4, CLAUDE.md uslubida.
 * ConnectionBadge · ApprovalCard · AuditRow · KillSwitchButton
 * Modal — .floating (blur faqat shu yerda ruxsat).
 */

import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";

import { Button, Eyebrow, Panel, StatusDot } from "@/components/ui/primitives";
import { sound } from "@/lib/sound";

/* ── Ulanish holati (docs/11 §2.1) ────────────────────────────── */

export type ConnectionState = "disconnected" | "connecting" | "connected" | "executing" | "error";

const CONN: Record<ConnectionState, { color: string; pulse: boolean; text: string }> = {
  disconnected: {
    color: "var(--text-muted)",
    pulse: false,
    text: "Ulanmagan — ZET agentni kompyuteringizda ishga tushiring",
  },
  connecting: { color: "var(--status-working)", pulse: true, text: "Ulanmoqda…" },
  connected: { color: "var(--status-online)", pulse: false, text: "Ulangan" },
  executing: { color: "var(--accent-blue)", pulse: true, text: "Amal bajarilmoqda…" },
  error: { color: "var(--status-alert)", pulse: false, text: "Xato" },
};

export function ConnectionBadge({ state, detail }: { state: ConnectionState; detail?: string }) {
  const c = CONN[state];
  return (
    <div className="inline-flex items-center gap-2.5 rounded-full border border-[var(--border-hairline)] bg-[var(--bg-elevated)] px-4 py-2">
      <StatusDot color={c.color} pulse={c.pulse} />
      <span className="text-sm text-[var(--text-primary)]">
        {c.text}
        {detail ? <span className="text-[var(--text-secondary)]"> — {detail}</span> : null}
      </span>
    </div>
  );
}

/* ── Approval karta (docs/11 §2.4, V-32) ──────────────────────── */

export interface ApprovalInfo {
  id: string;
  toolName: string;
  reason: string;
  preview: Record<string, unknown>;
  expiresAt: string;
}

function useCountdown(expiresAt: string) {
  const [left, setLeft] = useState(() => new Date(expiresAt).getTime() - Date.now());
  useEffect(() => {
    const t = setInterval(() => setLeft(new Date(expiresAt).getTime() - Date.now()), 1000);
    return () => clearInterval(t);
  }, [expiresAt]);
  return Math.max(0, left);
}

export function ApprovalCard({
  approval,
  ttlMinutes = 30,
  onApprove,
  onReject,
}: {
  approval: ApprovalInfo;
  ttlMinutes?: number;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}) {
  const leftMs = useCountdown(approval.expiresAt);
  const expired = leftMs <= 0;
  const mm = Math.floor(leftMs / 60000);
  const ss = Math.floor((leftMs % 60000) / 1000);
  const frac = Math.min(1, leftMs / (ttlMinutes * 60000));

  useEffect(() => {
    sound.play("approval");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
    >
      <Panel className={`p-5 ${expired ? "opacity-60" : "!border-[var(--border-active)]"}`}>
        <div className="flex items-center gap-2">
          <StatusDot color={expired ? "var(--text-muted)" : "var(--status-working)"} pulse={!expired} />
          <Eyebrow className="!text-[var(--status-working)]">
            {expired ? "Muddat tugadi" : "Tasdiq kutilmoqda"}
          </Eyebrow>
        </div>

        <div className="data mt-3 text-sm text-[var(--accent-blue)]">{approval.toolName}</div>
        <div className="mt-1 text-sm text-[var(--text-secondary)]">{approval.reason}</div>

        {Object.keys(approval.preview).length > 0 ? (
          <div className="mt-3 rounded-[10px] border border-[var(--border-hairline)] bg-[var(--bg-base)] p-3">
            {Object.entries(approval.preview).map(([k, v]) => (
              <div key={k} className="data flex gap-2 text-xs">
                <span className="text-[var(--text-muted)]">{k}:</span>
                <span className="break-all text-[var(--text-primary)]">{String(v)}</span>
              </div>
            ))}
          </div>
        ) : null}

        <div className="mt-4">
          <div className="flex items-center justify-between text-xs">
            <span className="text-[var(--text-muted)]">Muddat</span>
            <span className="data text-[var(--text-secondary)]">
              {expired ? "00:00" : `${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`}
            </span>
          </div>
          <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-[var(--surface-hover)]">
            <div
              className="h-full rounded-full transition-[width] duration-1000 ease-linear"
              style={{
                width: `${frac * 100}%`,
                background: frac < 0.2 ? "var(--status-alert)" : "var(--status-working)",
              }}
            />
          </div>
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <Button variant="danger" disabled={expired} onClick={() => onReject(approval.id)}>
            Rad etish
          </Button>
          <Button variant="primary" disabled={expired} onClick={() => onApprove(approval.id)}>
            Tasdiqlash
          </Button>
        </div>
        {expired ? (
          <div className="mt-2 text-right text-xs text-[var(--text-muted)]">
            Muddat tugadi — amalni qayta so'rang
          </div>
        ) : null}
      </Panel>
    </motion.div>
  );
}

/* ── Audit log qatori (docs/11 §2.5) ──────────────────────────── */

export type AuditOutcome = "done" | "rejected" | "pending" | "expired";

const AUDIT: Record<AuditOutcome, { color: string; text: string }> = {
  done: { color: "var(--status-online)", text: "bajarildi" },
  rejected: { color: "var(--status-alert)", text: "rad etildi" },
  pending: { color: "var(--status-working)", text: "kutilmoqda" },
  expired: { color: "var(--text-muted)", text: "muddat tugadi" },
};

export function AuditRow({
  time,
  tool,
  detail,
  outcome,
  latencyMs,
}: {
  time: string;
  tool: string;
  detail: string;
  outcome: AuditOutcome;
  latencyMs?: number;
}) {
  const a = AUDIT[outcome];
  return (
    <div className="data flex items-baseline gap-3 border-b border-[var(--border-hairline)] py-2 text-xs last:border-0">
      <span className="shrink-0 text-[var(--text-muted)]">[{time}]</span>
      <span className="shrink-0 text-[var(--accent-blue)]">{tool}</span>
      <span className="min-w-0 flex-1 truncate text-[var(--text-secondary)]">{detail}</span>
      <span className="shrink-0" style={{ color: a.color }}>
        {a.text}
        {outcome === "done" && latencyMs != null ? ` (${latencyMs}ms)` : ""}
      </span>
    </div>
  );
}

/* ── Kill-switch (docs/11 §2.6) ───────────────────────────────── */

export function KillSwitchButton({
  engaged,
  onEngage,
  onDisengage,
}: {
  engaged: boolean;
  onEngage: () => void;
  onDisengage: () => void;
}) {
  const [confirming, setConfirming] = useState(false);

  if (engaged) {
    return (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="flex items-center justify-between gap-4 rounded-[var(--radius-card)] border border-[var(--status-alert)] bg-[rgba(239,68,68,0.06)] px-4 py-3"
      >
        <div className="flex items-center gap-2.5">
          <StatusDot color="var(--status-alert)" pulse />
          <span className="data text-sm font-medium text-[var(--status-alert)]">
            KILLSWITCH FAOL — barcha amallar to'xtatilgan
          </span>
        </div>
        <Button variant="ghost" onClick={onDisengage}>
          Qayta yoqish
        </Button>
      </motion.div>
    );
  }

  return (
    <>
      <Button variant="danger" onClick={() => setConfirming(true)}>
        Barcha amallarni to'xtatish
      </Button>
      <AnimatePresence>
        {confirming ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(5,6,8,0.7)]"
            onClick={() => setConfirming(false)}
          >
            <motion.div
              initial={{ scale: 0.96, y: 6 }}
              animate={{ scale: 1, y: 0 }}
              exit={{ scale: 0.96, opacity: 0 }}
              transition={{ type: "spring", stiffness: 300, damping: 30 }}
              onClick={(e) => e.stopPropagation()}
              className="floating w-[380px] p-6"
            >
              <Eyebrow className="!text-[var(--status-alert)]">Favqulodda to'xtatish</Eyebrow>
              <p className="mt-3 text-sm text-[var(--text-primary)]">
                Barcha faol run'lar bir zumda to'xtatiladi. Ishonchingiz komilmi?
              </p>
              <div className="mt-5 flex justify-end gap-2">
                <Button variant="ghost" onClick={() => setConfirming(false)}>
                  Bekor qilish
                </Button>
                <Button
                  variant="danger"
                  onClick={() => {
                    sound.play("killswitch");
                    setConfirming(false);
                    onEngage();
                  }}
                >
                  To'xtatish
                </Button>
              </div>
            </motion.div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </>
  );
}
