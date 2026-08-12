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
import { api } from "@/lib/api";
import { haptic, initTelegramApp } from "@/lib/telegram";
import { useBackendHealth } from "@/lib/useBackendHealth";
import { useResource } from "@/lib/useResource";
import { sound } from "@/lib/sound";

type Tab = "chat" | "agents" | "tasks" | "camera" | "settings";

const TABS: { id: Tab; icon: typeof Bot; label: string }[] = [
  { id: "chat", icon: MessageCircle, label: "Chat" },
  { id: "agents", icon: Bot, label: "Agentlar" },
  { id: "tasks", icon: ListChecks, label: "Vazifalar" },
  { id: "camera", icon: CameraIcon, label: "Kamera" },
  { id: "settings", icon: Settings, label: "Sozlash" },
];

function ChatTab() {
  const [input, setInput] = useState("");
  const [listening, setListening] = useState(true);
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);
  return (
    <div className="flex h-full flex-col items-center justify-between py-6">
      <div className="flex flex-1 flex-col items-center justify-center">
        <button
          aria-label="ZET"
          className="h-40 w-40"
          onClick={() => {
            haptic("light");
            sound.play(listening ? "sleep" : "wake");
            setListening((v) => !v);
          }}
        >
          <NeuroOrb state={listening ? "listening" : "idle"} className="h-full w-full" />
        </button>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          {sending
            ? "O'ylayapman…"
            : reply || (listening ? "Eshityapman…" : "Qanday yordam beray?")}
        </p>
      </div>
      <CommandInput
        value={input}
        onChange={setInput}
        placeholder="Buyruq yozing…"
        disabled={sending}
        onSubmit={() => {
          const text = input.trim();
          if (!text || sending) return;
          haptic("medium");
          setInput("");
          setSending(true);
          setReply("");
          // Ilgari bu yerda faqat `setInput("")` bor edi — yozilgan
          // xabar hech qayerga bormay yo'qolardi.
          void api.run(text, "tg").then((res) => {
            setReply(res.ok ? res.data.message : `Xato: ${res.error}`);
            setSending(false);
          });
        }}
      />
    </div>
  );
}

/** Backend `AgentStatus` → UI holati.
 *
 * "working"/"thinking" ATAYIN yo'q: backend jonli signal bermaydi,
 * shuning uchun ular o'ylab topilgan holat bo'lardi. Ilgari bu
 * sahifada aynan shu ikkisi qotirilgan edi. */
function toUiStatus(status: string): "online" | "offline" | "paused" {
  if (status === "active") return "online";
  if (status === "paused") return "paused";
  return "offline";
}

function AgentsTab() {
  const { state } = useResource(() => api.agents(), 20_000);
  return (
    <div className="space-y-3 py-4">
      <Eyebrow>Agentlar</Eyebrow>
      <Panel className="p-2">
        {state.kind === "loading" ? (
          <p className="px-3 py-4 text-xs text-[var(--text-muted)]">Yuklanmoqda…</p>
        ) : null}
        {state.kind === "error" ? (
          <p className="px-3 py-4 text-xs text-[var(--status-alert)]">{state.message}</p>
        ) : null}
        {state.kind === "ready" && state.data.length === 0 ? (
          <p className="px-3 py-4 text-xs text-[var(--text-muted)]">Agent yo&apos;q</p>
        ) : null}
        {state.kind === "ready"
          ? state.data.map((a) => (
              <AgentListItem
                key={a.name}
                name={a.name}
                division={a.division}
                status={toUiStatus(a.status)}
              />
            ))
          : null}
      </Panel>
    </div>
  );
}

function TasksTab() {
  const { state } = useResource(() => api.tasks.list(), 20_000);
  const tasks = state.kind === "ready" ? state.data : [];
  const done = tasks.filter((t) => t.status === "done").length;
  // Ilgari bu `percent={68}` — qotirilgan son edi.
  const percent = tasks.length ? Math.round((done / tasks.length) * 100) : 0;

  return (
    <div className="space-y-4 py-4">
      <div className="flex items-center justify-between">
        <Eyebrow>Vazifalar</Eyebrow>
        {tasks.length ? <ProgressRing percent={percent} size={52} /> : null}
      </div>
      <Panel className="p-2">
        {state.kind === "loading" ? (
          <p className="px-3 py-4 text-xs text-[var(--text-muted)]">Yuklanmoqda…</p>
        ) : null}
        {state.kind === "error" ? (
          <p className="px-3 py-4 text-xs text-[var(--status-alert)]">{state.message}</p>
        ) : null}
        {state.kind === "ready" && tasks.length === 0 ? (
          <p className="px-3 py-4 text-xs text-[var(--text-muted)]">Vazifa yo&apos;q</p>
        ) : null}
        {tasks.map((t) => (
          <div
            key={t.id}
            className="flex items-baseline gap-3 rounded-[10px] px-3 py-2.5 transition-colors hover:bg-[var(--surface-hover)]"
          >
            <span className="data shrink-0 text-[10px] text-[var(--accent-blue)]">
              {t.status === "done" ? "✓" : t.priority}
            </span>
            <span
              className={`text-sm ${
                t.status === "done"
                  ? "text-[var(--text-muted)] line-through"
                  : "text-[var(--text-primary)]"
              }`}
            >
              {t.title}
            </span>
          </div>
        ))}
      </Panel>
    </div>
  );
}

function CameraTab() {
  return (
    <div className="space-y-3 py-4">
      <Eyebrow>Kamera</Eyebrow>
      {/* Ilgari to'rtta o'ylab topilgan kamera nomi ("Old eshik",
          "Hovli", "Garaj", "Ofis") ko'rsatilardi. Sozlamada esa
          BITTA Hikvision kanali bor xolos — ko'p kamerali ro'yxat
          shunchaki to'qilgan edi. */}
      <div className="grid grid-cols-1 gap-3">
        {["Asosiy kanal"].map((c) => (
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
  const health = useBackendHealth();

  useEffect(() => {
    initTelegramApp();
  }, []);

  return (
    <div className="mx-auto flex h-dvh max-w-md flex-col px-4">
      {/* Sarlavha */}
      <header className="flex items-center justify-between py-3">
        <span className="text-sm font-semibold tracking-[0.2em] text-[var(--text-primary)]">ZET</span>
        {/* Ilgari bu QOTIRILGAN yashil "Onlayn" edi — backend o'chiq
            bo'lsa ham shunday ko'rinardi. Endi haqiqiy tekshiruvdan. */}
        <div className="flex items-center gap-1.5">
          <StatusDot
            color={
              health === "online"
                ? "var(--status-online)"
                : health === "checking"
                  ? "var(--status-working)"
                  : "var(--status-alert)"
            }
          />
          <span className="text-[10px] text-[var(--text-secondary)]">
            {health === "online" ? "Onlayn" : health === "checking" ? "Tekshirilmoqda" : "Aloqa yo'q"}
          </span>
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
