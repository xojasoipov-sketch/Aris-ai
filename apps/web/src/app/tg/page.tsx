"use client";

/** Telegram Mini App (/tg) — FAZA 5 speci (mockup pastki qatori: 6 ekran).
 *
 * Bir ustunli, 100vw/100vh, pastda tab-bar. Xuddi shu komponentlar
 * kichraytirilgan holda: Chat (orb + input), Agentlar, Vazifalar,
 * Kamera, Sozlamalar.
 *
 * WebApp.initData autentifikatsiyasi backend'da tekshiriladi (R-04);
 * Telegram tashqarisida oddiy brauzerda ham ishlaydi (demo).
 */

import { Bot, Camera as CameraIcon, ListChecks, MessageCircle, Settings } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";

import { NeuroOrb } from "@/components/core/NeuroOrb";
import { AgentListItem, ProgressRing } from "@/components/ui/cards";
import { CommandInput } from "@/components/ui/CommandInput";
import { Eyebrow, Panel, StatusDot } from "@/components/ui/primitives";
import { haptic, initTelegramApp } from "@/lib/telegram";
import { sound } from "@/lib/sound";

type Tab = "chat" | "agents" | "tasks" | "camera" | "settings";

const TABS: { id: Tab; icon: typeof Bot; label: string }[] = [
  { id: "chat", icon: MessageCircle, label: "Chat" },
  { id: "agents", icon: Bot, label: "Agentlar" },
  { id: "tasks", icon: ListChecks, label: "Vazifalar" },
  { id: "camera", icon: CameraIcon, label: "Kamera" },
  { id: "settings", icon: Settings, label: "Sozlash" },
];

const AGENTS = [
  { name: "CEO Agent", division: "Strategiya", status: "online" },
  { name: "SMM Agent", division: "Marketing", status: "working" },
  { name: "Developer Agent", division: "Texnologiya", status: "online" },
  { name: "Research Agent", division: "Intellekt", status: "thinking" },
  { name: "HR Agent", division: "Boshqaruv", status: "offline" },
] as const;

const TASKS = [
  { time: "10:00", title: "SMM strategiyani yangilash" },
  { time: "12:30", title: "Analitika hisobotini tayyorlash" },
  { time: "14:00", title: "Loyiha ko'rigi" },
  { time: "16:00", title: "Mijoz uchun taklif tayyorlash" },
  { time: "18:30", title: "Zaxira nusxasini yaratish" },
] as const;

const CAMERAS = ["Old eshik", "Hovli", "Garaj", "Ofis"] as const;

function ChatTab() {
  const [input, setInput] = useState("");
  const [listening, setListening] = useState(true);
  return (
    <div className="flex h-full flex-col items-center justify-between py-6">
      <div className="flex flex-1 flex-col items-center justify-center">
        <button
          aria-label="ZET"
          className="h-52 w-52"
          onClick={() => {
            haptic("light");
            sound.play(listening ? "sleep" : "wake");
            setListening((v) => !v);
          }}
        >
          <NeuroOrb state={listening ? "listening" : "idle"} className="h-full w-full" />
        </button>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          {listening ? "Eshityapman…" : "Qanday yordam beray?"}
        </p>
      </div>
      <CommandInput
        value={input}
        onChange={setInput}
        placeholder="Buyruq yozing…"
        onSubmit={() => {
          haptic("medium");
          setInput("");
        }}
      />
    </div>
  );
}

function AgentsTab() {
  return (
    <div className="space-y-3 py-4">
      <Eyebrow>Faol agentlar</Eyebrow>
      <Panel className="p-2">
        {AGENTS.map((a) => (
          <AgentListItem key={a.name} {...a} />
        ))}
      </Panel>
    </div>
  );
}

function TasksTab() {
  return (
    <div className="space-y-4 py-4">
      <div className="flex items-center justify-between">
        <Eyebrow>Bugungi vazifalar</Eyebrow>
        <ProgressRing percent={68} size={52} />
      </div>
      <Panel className="p-2">
        {TASKS.map((t) => (
          <div
            key={t.time}
            className="flex items-baseline gap-3 rounded-[10px] px-3 py-2.5 transition-colors hover:bg-[var(--surface-hover)]"
          >
            <span className="data shrink-0 text-xs text-[var(--accent-blue)]">{t.time}</span>
            <span className="text-sm text-[var(--text-primary)]">{t.title}</span>
          </div>
        ))}
      </Panel>
    </div>
  );
}

function CameraTab() {
  return (
    <div className="space-y-3 py-4">
      <Eyebrow>Kameralar</Eyebrow>
      <div className="grid grid-cols-2 gap-3">
        {CAMERAS.map((c) => (
          <div
            key={c}
            className="relative aspect-video overflow-hidden rounded-[12px] border border-[var(--border-hairline)] bg-[var(--bg-base)]"
          >
            <div className="absolute left-2 top-1.5 flex items-center gap-1.5">
              <StatusDot color="var(--status-offline)" />
              <span className="text-[10px] text-[var(--text-secondary)]">{c}</span>
            </div>
            <span className="data absolute bottom-1.5 right-2 text-[9px] text-[var(--text-muted)]">
              signal yo'q
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function SettingsTab() {
  return (
    <div className="space-y-3 py-4">
      <Eyebrow>Sozlamalar</Eyebrow>
      <Panel className="px-4 py-1">
        {[
          ["Til", "O'zbekcha"],
          ["Tungi rejim", "Yoqilgan"],
          ["Bildirishnomalar", "Yoqilgan"],
          ["Ovozli javob", "ElevenLabs"],
        ].map(([k, v]) => (
          <div
            key={k}
            className="flex items-center justify-between border-b border-[var(--border-hairline)] py-3 last:border-0"
          >
            <span className="text-sm text-[var(--text-primary)]">{k}</span>
            <span className="text-xs text-[var(--text-secondary)]">{v}</span>
          </div>
        ))}
      </Panel>
      <p className="px-1 text-[10px] leading-relaxed text-[var(--text-muted)]">
        To'liq boshqaruv — web dashboard'da. Bu Mini App tezkor nazorat uchun.
      </p>
    </div>
  );
}

export default function TgPage() {
  const [tab, setTab] = useState<Tab>("chat");

  useEffect(() => {
    initTelegramApp();
  }, []);

  return (
    <div className="mx-auto flex h-dvh max-w-md flex-col px-4">
      {/* Sarlavha */}
      <header className="flex items-center justify-between py-3">
        <span className="text-sm font-semibold tracking-[0.2em] text-[var(--text-primary)]">ZET</span>
        <div className="flex items-center gap-1.5">
          <StatusDot color="var(--status-online)" />
          <span className="text-[10px] text-[var(--text-secondary)]">Onlayn</span>
        </div>
      </header>

      {/* Kontent */}
      <main className="min-h-0 flex-1 overflow-y-auto">
        <AnimatePresence mode="wait">
          <motion.div
            key={tab}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.25, ease: "easeOut" }}
            className="h-full"
          >
            {tab === "chat" ? <ChatTab /> : null}
            {tab === "agents" ? <AgentsTab /> : null}
            {tab === "tasks" ? <TasksTab /> : null}
            {tab === "camera" ? <CameraTab /> : null}
            {tab === "settings" ? <SettingsTab /> : null}
          </motion.div>
        </AnimatePresence>
      </main>

      {/* Bottom tab-bar */}
      <nav className="flex items-stretch justify-around border-t border-[var(--border-hairline)] bg-[var(--bg-elevated)] pb-[env(safe-area-inset-bottom)]">
        {TABS.map(({ id, icon: I, label }) => (
          <button
            key={id}
            onClick={() => {
              haptic("light");
              sound.play("tick");
              setTab(id);
            }}
            className={`flex flex-1 flex-col items-center gap-0.5 border-t-2 py-2 text-[10px] ${
              tab === id
                ? "border-[var(--accent-blue)] text-[var(--text-primary)]"
                : "border-transparent text-[var(--text-muted)]"
            }`}
          >
            <I size={18} strokeWidth={1.5} className={tab === id ? "text-[var(--accent-blue)]" : ""} />
            {label}
          </button>
        ))}
      </nav>
    </div>
  );
}
