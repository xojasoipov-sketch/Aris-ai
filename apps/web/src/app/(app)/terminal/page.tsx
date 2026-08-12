"use client";

/** Terminal (/terminal) — FAZA 4 speci: dev-terminal uslubidagi jonli
 * log/status oqimi (monospace). Tab: Terminal/Loglar/Tizim.
 * Real observability stream keyin ulanadi.
 */

import { motion } from "motion/react";
import { useEffect, useRef, useState } from "react";

import { Eyebrow, Panel } from "@/components/ui/primitives";
import { Tabs } from "@/components/ui/Tabs";
import { sound } from "@/lib/sound";

const TABS = ["Terminal", "Loglar", "Tizim"] as const;

interface Line {
  id: number;
  text: string;
  color?: string;
}

const SEED_LINES: Omit<Line, "id">[] = [
  { text: "zet@core:~$ tizim holati", color: "var(--text-primary)" },
  { text: "Tizim: ONLAYN", color: "var(--status-online)" },
  { text: "Uptime: 24:13:22" },
  { text: "CPU: 24% · RAM: 41% · GPU: 15%" },
  { text: "Faol agentlar: 4 / 6" },
  { text: "Bajarilayotgan vazifalar: 7" },
  { text: "Tarmoq: 120 Mbps" },
];

const STREAM_LINES: { text: string; color?: string }[] = [
  { text: "[orchestrator] intent aniqlandi: kanal_statistika", color: "var(--accent-blue)" },
  { text: "[router] T1 tanlandi (gemini-flash) — narx 0.0000$" },
  { text: "[tool] telegram.channel_stats chaqirildi (142ms)", color: "var(--text-secondary)" },
  { text: "[verifier] natija tasdiqlandi ✓", color: "var(--status-online)" },
  { text: "[memory] 3 ta yangi eslatma indekslandi" },
  { text: "[smm-agent] kontent-reja generatsiyasi boshlandi", color: "var(--accent-blue)" },
  { text: "[budget] kunlik sarf: $0.04 / $0.50", color: "var(--text-secondary)" },
  { text: "[scheduler] 08:00 briefing rejalashtirildi" },
];

export default function TerminalPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]>(TABS[0]);
  const [lines, setLines] = useState<Line[]>(SEED_LINES.map((l, i) => ({ ...l, id: i })));
  const nextId = useRef(SEED_LINES.length);
  const scrollRef = useRef<HTMLDivElement>(null);

  /* Jonli oqim — 2.5s da bir yangi qator (demo) */
  useEffect(() => {
    const t = setInterval(() => {
      const src = STREAM_LINES[Math.floor(Math.random() * STREAM_LINES.length)];
      const ts = new Date().toLocaleTimeString("uz-UZ", { hour12: false });
      setLines((cur) => [
        ...cur.slice(-60),
        { id: nextId.current++, text: `${ts} ${src.text}`, color: src.color },
      ]);
    }, 2500);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [lines]);

  return (
    <div className="mx-auto max-w-5xl space-y-5 px-6 py-6 lg:px-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Terminal</h1>
        <Tabs tabs={TABS} value={tab} onChange={setTab} />
      </div>

      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, ease: "easeOut" }}>
        <Panel className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-[var(--border-hairline)] px-4 py-2.5">
            <Eyebrow>zet@core — jonli oqim</Eyebrow>
            <span className="pulse-dot inline-block h-1.5 w-1.5 rounded-full bg-[var(--status-online)]" />
          </div>
          <div
            ref={scrollRef}
            className="data h-[420px] space-y-1 overflow-y-auto bg-[var(--bg-base)] p-4 text-xs leading-relaxed"
          >
            {lines.map((l) => (
              <div key={l.id} style={{ color: l.color ?? "var(--text-muted)" }}>
                {l.text}
              </div>
            ))}
            <div className="flex items-center gap-1 text-[var(--text-primary)]">
              zet@core:~$
              <span className="pulse-dot inline-block h-3.5 w-[7px] bg-[var(--accent-blue)]" />
            </div>
          </div>
        </Panel>
      </motion.div>
    </div>
  );
}
