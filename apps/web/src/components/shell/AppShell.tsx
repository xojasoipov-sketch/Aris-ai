"use client";

/** App shell — chap sidebar + yuqori bar + kontent (docs/10 §3.1, §4).
 * Sidebar tartibi mockup bo'yicha: 12 sahifa.
 */

import { motion } from "framer-motion";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import {
  IconAgents,
  IconAnalytics,
  IconAssistant,
  IconBell,
  IconCalendar,
  IconCamera,
  IconDashboard,
  IconDevices,
  IconFiles,
  IconMessages,
  IconProjects,
  IconSearch,
  IconSettings,
  IconTasks,
  IconVolume,
  IconVolumeOff,
} from "@/components/ui/icons";
import { sound } from "@/lib/sound";

const NAV = [
  { href: "/", label: "Boshqaruv", icon: IconDashboard },
  { href: "/assistant", label: "AI Yordamchi", icon: IconAssistant },
  { href: "/agents", label: "Agentlar", icon: IconAgents },
  { href: "/projects", label: "Loyihalar", icon: IconProjects },
  { href: "/calendar", label: "Taqvim", icon: IconCalendar },
  { href: "/tasks", label: "Vazifalar", icon: IconTasks },
  { href: "/messages", label: "Xabarlar", icon: IconMessages },
  { href: "/files", label: "Fayllar", icon: IconFiles },
  { href: "/analytics", label: "Analitika", icon: IconAnalytics },
  { href: "/devices", label: "Qurilmalar", icon: IconDevices },
  { href: "/camera", label: "Kamera", icon: IconCamera },
  { href: "/settings", label: "Sozlamalar", icon: IconSettings },
] as const;

function Clock() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  if (!now) return <div className="h-10 w-24" />;
  return (
    <div>
      <div className="tabular font-mono text-lg font-semibold text-[var(--text-primary)]">
        {now.toLocaleTimeString("uz-UZ", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
      </div>
      <div className="text-[11px] text-[var(--text-muted)]">
        {now.toLocaleDateString("uz-UZ", { day: "numeric", month: "long", year: "numeric" })}
      </div>
    </div>
  );
}

function SoundToggle() {
  const [on, setOn] = useState(true);
  useEffect(() => setOn(sound.enabled), []);
  return (
    <button
      aria-label={on ? "Ovozni o'chirish" : "Ovozni yoqish"}
      className="rounded-lg p-2 text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)]"
      onClick={() => {
        const next = !on;
        sound.setEnabled(next);
        setOn(next);
        if (next) sound.play("tick");
      }}
    >
      {on ? <IconVolume /> : <IconVolumeOff />}
    </button>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen">
      {/* ── Sidebar ── */}
      <aside className="fixed inset-y-0 left-0 z-40 flex w-56 flex-col border-r border-[var(--border-subtle)] bg-[var(--bg-surface)]">
        {/* Logo — zarrachali doira + ZET wordmark */}
        <Link href="/" className="flex items-center gap-3 px-5 py-5">
          <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden>
            {Array.from({ length: 24 }, (_, i) => {
              const a = (i / 24) * Math.PI * 2;
              const r = i % 2 === 0 ? 11 : 8;
              return (
                <circle
                  key={i}
                  cx={14 + r * Math.cos(a)}
                  cy={14 + r * Math.sin(a)}
                  r="0.9"
                  fill="var(--accent-cyan)"
                  opacity={i % 2 === 0 ? 0.9 : 0.45}
                />
              );
            })}
          </svg>
          <span className="text-lg font-bold tracking-[0.2em] text-[var(--text-primary)]">ZET</span>
        </Link>

        <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 pb-4">
          {NAV.map(({ href, label, icon: I }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                onClick={() => sound.play("tick")}
                className={`relative flex items-center gap-3 rounded-[10px] px-3 py-2 text-sm transition-colors ${
                  active
                    ? "text-[var(--text-primary)]"
                    : "text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)]"
                }`}
              >
                {active ? (
                  <motion.span
                    layoutId="nav-active"
                    className="absolute inset-0 rounded-[10px] bg-[var(--bg-elevated)] ring-1 ring-[var(--border-glow)]"
                    transition={{ type: "spring", stiffness: 400, damping: 32 }}
                  />
                ) : null}
                <span className={`relative ${active ? "text-[var(--accent-primary)]" : ""}`}>
                  <I />
                </span>
                <span className="relative">{label}</span>
              </Link>
            );
          })}
        </nav>

        {/* Egasi paneli */}
        <div className="border-t border-[var(--border-subtle)] px-5 py-4">
          <div className="flex items-center gap-2.5">
            <span className="inline-block h-2 w-2 rounded-full bg-[var(--state-online)]" />
            <div>
              <div className="text-sm font-medium text-[var(--text-primary)]">Ega</div>
              <div className="text-[11px] text-[var(--text-muted)]">Onlayn</div>
            </div>
          </div>
        </div>
      </aside>

      {/* ── Asosiy qism ── */}
      <div className="ml-56 flex min-h-screen flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center justify-between gap-6 border-b border-[var(--border-subtle)] bg-[rgba(5,7,13,0.75)] px-8 py-3 backdrop-blur-md">
          <Clock />
          <div className="glass flex max-w-md flex-1 items-center gap-2.5 rounded-full px-4 py-2">
            <IconSearch className="text-[var(--text-muted)]" />
            <input
              placeholder="Istalgan narsani qidiring..."
              className="w-full bg-transparent text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)]"
            />
          </div>
          <div className="flex items-center gap-1">
            <SoundToggle />
            <button
              aria-label="Bildirishnomalar"
              className="rounded-lg p-2 text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)]"
            >
              <IconBell />
            </button>
          </div>
        </header>
        <main className="flex-1">{children}</main>
      </div>
    </div>
  );
}
