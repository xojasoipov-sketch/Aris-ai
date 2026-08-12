"use client";

/** Komponent ko'rgazmasi — har bir UI element izolyatsiyada (docs/10 §6 qadam 2).
 * Bu sahifa faqat development uchun — production nav'da ko'rinmaydi.
 */

import { useState } from "react";

import { AgentListItem, ProgressRing, Sparkline, StatCard } from "@/components/ui/cards";
import {
  ApprovalCard,
  AuditRow,
  ConnectionBadge,
  KillSwitchButton,
  type ConnectionState,
} from "@/components/ui/devices";
import { Button, GlassPanel, TechLabel } from "@/components/ui/primitives";
import { StatusPill, type PillKind } from "@/components/ui/StatusPill";
import { sound } from "@/lib/sound";

const PILLS: PillKind[] = ["thinking", "searching", "solving", "shaping", "listening"];
const CONN_STATES: ConnectionState[] = [
  "disconnected",
  "connecting",
  "connected",
  "executing",
  "error",
];

export default function ComponentsPage() {
  const [killswitch, setKillswitch] = useState(false);
  const [approvalKey, setApprovalKey] = useState(0);

  return (
    <main className="mx-auto max-w-4xl space-y-10 px-6 py-10">
      <header>
        <h1 className="text-2xl font-bold">ZET komponent library</h1>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          docs/10 §3 va docs/11 §4 komponentlari — izolyatsiyada
        </p>
      </header>

      <section className="space-y-3">
        <TechLabel>Status pill (docs/10 §3.3)</TechLabel>
        <div className="flex flex-wrap gap-3">
          {PILLS.map((k) => (
            <StatusPill key={k} kind={k} />
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <TechLabel>Stat kartalar</TechLabel>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <StatCard label="Loyihalar" value={12} hint="faol" />
          <StatCard label="Agentlar" value={24} hint="onlayn" />
          <StatCard label="Vazifalar" value="68%" hint="bajarilgan" />
          <StatCard label="Tizim" value={87} hint="optimal" />
        </div>
      </section>

      <section className="space-y-3">
        <TechLabel>Agent ro'yxati</TechLabel>
        <GlassPanel className="p-2">
          <AgentListItem name="CEO Agent" division="Strategiya" status="online" />
          <AgentListItem name="SMM Agent" division="Marketing" status="working" />
          <AgentListItem name="Developer Agent" division="Texnologiya" status="online" />
          <AgentListItem name="Research Agent" division="Intellekt" status="thinking" />
          <AgentListItem name="Finance Agent" division="Moliya" status="offline" />
          <AgentListItem name="HR Agent" division="Boshqaruv" status="paused" />
        </GlassPanel>
      </section>

      <section className="space-y-3">
        <TechLabel>Progress ring + sparkline</TechLabel>
        <div className="flex items-center gap-8">
          <ProgressRing percent={68} label="bajarildi" />
          <GlassPanel className="p-4">
            <TechLabel>CPU</TechLabel>
            <Sparkline data={[24, 31, 28, 45, 38, 52, 41, 36, 48, 44, 39, 55]} />
          </GlassPanel>
        </div>
      </section>

      <section className="space-y-3">
        <TechLabel>Ulanish holatlari (docs/11 §2.1)</TechLabel>
        <div className="flex flex-wrap gap-3">
          {CONN_STATES.map((s) => (
            <ConnectionBadge key={s} state={s} detail={s === "connected" ? "MacBook Pro, macOS" : undefined} />
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <TechLabel>Approval karta (docs/11 §2.4)</TechLabel>
        <div className="max-w-md">
          <ApprovalCard
            key={approvalKey}
            approval={{
              id: "demo",
              toolName: "desktop.key_press",
              reason: "Terminal ochish uchun hotkey",
              preview: { keys: "ctrl+alt+t" },
              expiresAt: new Date(Date.now() + 90_000).toISOString(),
            }}
            ttlMinutes={30}
            onApprove={() => {
              sound.play("success");
              setApprovalKey((k) => k + 1);
            }}
            onReject={() => {
              sound.play("error");
              setApprovalKey((k) => k + 1);
            }}
          />
        </div>
      </section>

      <section className="space-y-3">
        <TechLabel>Audit log (docs/11 §2.5)</TechLabel>
        <GlassPanel className="px-4 py-2">
          <AuditRow time="12:04:12" tool="desktop.key_press" detail="ctrl+alt+t" outcome="done" latencyMs={140} />
          <AuditRow time="12:03:55" tool="desktop.type_text" detail="Salom dunyo" outcome="rejected" />
          <AuditRow time="12:03:31" tool="desktop.mouse_click" detail="x=340 y=220 left" outcome="pending" />
          <AuditRow time="11:58:02" tool="desktop.screenshot" detail="—" outcome="expired" />
        </GlassPanel>
      </section>

      <section className="space-y-3">
        <TechLabel>Kill-switch (docs/11 §2.6)</TechLabel>
        <KillSwitchButton
          engaged={killswitch}
          onEngage={() => setKillswitch(true)}
          onDisengage={() => setKillswitch(false)}
        />
      </section>

      <section className="space-y-3">
        <TechLabel>Tovushlar (lib/sound.ts)</TechLabel>
        <div className="flex flex-wrap gap-2">
          {(["wake", "sleep", "listenStart", "speak", "success", "error", "approval", "notification", "tick", "killswitch"] as const).map(
            (s) => (
              <Button key={s} onClick={() => sound.play(s)}>
                {s}
              </Button>
            ),
          )}
          <Button onClick={() => sound.startThinking()}>thinking ▶</Button>
          <Button onClick={() => sound.stopThinking()}>thinking ■</Button>
        </div>
      </section>
    </main>
  );
}
