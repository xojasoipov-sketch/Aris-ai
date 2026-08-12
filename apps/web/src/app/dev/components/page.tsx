"use client";

/** Komponent ko'rgazmasi v2 — har element izolyatsiyada (CLAUDE.md audit uchun).
 * NeuroOrb 6 holati + AgentStatusChip 5 turi shu yerda ko'zdan kechiriladi.
 */

import { useState } from "react";

import { NeuroOrb, type OrbState } from "@/components/core/NeuroOrb";
import { AgentStatusChip, type ChipKind } from "@/components/ui/AgentStatusChip";
import {
  AgentListItem,
  ProgressRing,
  RadialGauge,
  Sparkline,
  StatCard,
} from "@/components/ui/cards";
import {
  ApprovalCard,
  AuditRow,
  ConnectionBadge,
  KillSwitchButton,
  type ConnectionState,
} from "@/components/ui/devices";
import { Button, Eyebrow, Panel } from "@/components/ui/primitives";
import { sound } from "@/lib/sound";

const ORB_STATES: OrbState[] = ["idle", "listening", "thinking", "speaking", "searching", "offline"];
const CHIPS: ChipKind[] = ["thinking", "solving", "working", "listening", "searching"];
const CONN_STATES: ConnectionState[] = ["disconnected", "connecting", "connected", "executing", "error"];

export default function ComponentsPage() {
  const [killswitch, setKillswitch] = useState(false);
  const [approvalKey, setApprovalKey] = useState(0);
  const [orbState, setOrbState] = useState<OrbState>("idle");

  return (
    <main className="mx-auto max-w-4xl space-y-10 px-6 py-10">
      <header>
        <h1 className="text-2xl font-semibold">ZET komponent library</h1>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          CLAUDE.md master tizim — izolyatsiya ko'rgazmasi
        </p>
      </header>

      <section className="space-y-3">
        <Eyebrow>NeuroOrb — 6 holat (bosib almashtiring)</Eyebrow>
        <div className="flex flex-wrap gap-2">
          {ORB_STATES.map((s) => (
            <Button
              key={s}
              variant={s === orbState ? "primary" : "ghost"}
              onClick={() => setOrbState(s)}
            >
              {s}
            </Button>
          ))}
        </div>
        <Panel className="flex items-center justify-center p-4">
          <NeuroOrb state={orbState} className="h-[300px] w-[300px]" />
        </Panel>
      </section>

      <section className="space-y-3">
        <Eyebrow>AgentStatusChip — bitta shader, 5 variant</Eyebrow>
        <div className="flex flex-wrap gap-3">
          {CHIPS.map((k) => (
            <AgentStatusChip key={k} kind={k} />
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <Eyebrow>Stat kartalar</Eyebrow>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <StatCard label="Loyihalar" value={12} hint="faol" />
          <StatCard label="Agentlar" value={24} hint="onlayn" />
          <StatCard label="Vazifalar" value="68%" hint="bajarilgan" />
          <StatCard label="Tizim" value={87} hint="optimal" />
        </div>
      </section>

      <section className="space-y-3">
        <Eyebrow>Radial gauge + ring + sparkline</Eyebrow>
        <Panel className="flex items-center gap-8 p-4">
          <RadialGauge percent={24} label="CPU" value="24%" />
          <RadialGauge percent={68} label="GPU" value="68%" />
          <ProgressRing percent={68} label="bajarildi" />
          <Sparkline data={[24, 31, 28, 45, 38, 52, 41, 36, 48, 44, 39, 55]} id="demo" />
        </Panel>
      </section>

      <section className="space-y-3">
        <Eyebrow>Agent ro'yxati</Eyebrow>
        <Panel className="p-2">
          <AgentListItem name="CEO Agent" division="Strategiya" status="online" />
          <AgentListItem name="SMM Agent" division="Marketing" status="working" />
          <AgentListItem name="Research Agent" division="Intellekt" status="thinking" />
          <AgentListItem name="HR Agent" division="Boshqaruv" status="paused" />
        </Panel>
      </section>

      <section className="space-y-3">
        <Eyebrow>Ulanish holatlari</Eyebrow>
        <div className="flex flex-wrap gap-3">
          {CONN_STATES.map((s) => (
            <ConnectionBadge
              key={s}
              state={s}
              detail={s === "connected" ? "MacBook Pro, macOS" : undefined}
            />
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <Eyebrow>Approval karta</Eyebrow>
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
        <Eyebrow>Audit log</Eyebrow>
        <Panel className="px-4 py-2">
          <AuditRow time="12:04:12" tool="desktop.key_press" detail="ctrl+alt+t" outcome="done" latencyMs={140} />
          <AuditRow time="12:03:55" tool="desktop.type_text" detail="Salom dunyo" outcome="rejected" />
          <AuditRow time="12:03:31" tool="desktop.mouse_click" detail="x=340 y=220" outcome="pending" />
        </Panel>
      </section>

      <section className="space-y-3">
        <Eyebrow>Kill-switch</Eyebrow>
        <KillSwitchButton
          engaged={killswitch}
          onEngage={() => setKillswitch(true)}
          onDisengage={() => setKillswitch(false)}
        />
      </section>

      <section className="space-y-3">
        <Eyebrow>Tovushlar (WebAudio sintez)</Eyebrow>
        <div className="flex flex-wrap gap-2">
          {(
            ["wake", "sleep", "listenStart", "speak", "success", "error", "approval", "notification", "tick", "killswitch"] as const
          ).map((s) => (
            <Button key={s} onClick={() => sound.play(s)}>
              {s}
            </Button>
          ))}
          <Button onClick={() => sound.startThinking()}>thinking ▶</Button>
          <Button onClick={() => sound.stopThinking()}>thinking ■</Button>
        </div>
      </section>
    </main>
  );
}
