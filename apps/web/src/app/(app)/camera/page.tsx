"use client";

/** Kamera (/camera) — FAZA 4 speci: thumbnail grid, katta preview + PTZ,
 * preset ro'yxati, Live/Events/Timeline tab.
 *
 * Real oqim yo'q (devices/camera.py stub) — har karta "signal kutilmoqda"
 * holatida; Hikvision ulangach camera.snapshot shu grid'ga keladi.
 */

import {
  Camera as CameraIcon,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Circle,
} from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";

import { Eyebrow, Panel, StatusDot } from "@/components/ui/primitives";
import { Tabs } from "@/components/ui/Tabs";
import { sound } from "@/lib/sound";

const CAMERAS = ["Old eshik", "Hovli", "Garaj", "Ofis", "Ombor", "Turargoh"] as const;
const TABS = ["Jonli", "Voqealar", "Xronologiya"] as const;
const PRESETS = ["Uy", "Ofis", "Ombor", "Turargoh"] as const;

function CameraTile({
  name,
  active,
  onClick,
  large = false,
}: {
  name: string;
  active?: boolean;
  onClick?: () => void;
  large?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={`relative overflow-hidden rounded-[12px] border text-left transition-colors ${
        active ? "border-[var(--border-active)]" : "border-[var(--border-hairline)] hover:border-[var(--border-active)]"
      } ${large ? "aspect-video w-full" : "aspect-video"}`}
      style={{
        background:
          "radial-gradient(ellipse at 30% 20%, rgba(76,141,255,0.05), transparent 60%), var(--bg-base)",
      }}
    >
      <div className="absolute inset-0 flex items-center justify-center">
        <CameraIcon
          size={large ? 34 : 22}
          strokeWidth={1.5}
          className="text-[var(--text-muted)] opacity-50"
        />
      </div>
      <div className="absolute left-2.5 top-2 flex items-center gap-1.5">
        <StatusDot color="var(--status-offline)" />
        <span className="text-[10px] text-[var(--text-secondary)]">{name}</span>
      </div>
      <span className="data absolute bottom-2 right-2.5 text-[9px] text-[var(--text-muted)]">
        signal kutilmoqda
      </span>
    </button>
  );
}

export default function CameraPage() {
  const [selected, setSelected] = useState<(typeof CAMERAS)[number]>(CAMERAS[0]);
  const [tab, setTab] = useState<(typeof TABS)[number]>(TABS[0]);

  return (
    <div className="mx-auto max-w-6xl space-y-5 px-6 py-6 lg:px-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Kamera</h1>
        <Tabs tabs={TABS} value={tab} onChange={setTab} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_240px]">
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, ease: "easeOut" }} className="space-y-4">
          {/* Katta preview */}
          <CameraTile name={selected} large active />

          {/* Grid */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {CAMERAS.map((c) => (
              <CameraTile
                key={c}
                name={c}
                active={c === selected}
                onClick={() => {
                  sound.play("tick");
                  setSelected(c);
                }}
              />
            ))}
          </div>
        </motion.div>

        {/* PTZ + presetlar */}
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.07, duration: 0.35, ease: "easeOut" }} className="space-y-4">
          <Panel className="p-4">
            <Eyebrow>Kamera boshqaruvi</Eyebrow>
            <div className="mx-auto mt-4 grid w-32 grid-cols-3 gap-1.5">
              <span />
              <PtzBtn label="Yuqoriga">
                <ChevronUp size={16} strokeWidth={1.5} />
              </PtzBtn>
              <span />
              <PtzBtn label="Chapga">
                <ChevronLeft size={16} strokeWidth={1.5} />
              </PtzBtn>
              <PtzBtn label="Markaz">
                <Circle size={12} strokeWidth={1.5} />
              </PtzBtn>
              <PtzBtn label="O'ngga">
                <ChevronRight size={16} strokeWidth={1.5} />
              </PtzBtn>
              <span />
              <PtzBtn label="Pastga">
                <ChevronDown size={16} strokeWidth={1.5} />
              </PtzBtn>
              <span />
            </div>
            <p className="mt-3 text-center text-[10px] text-[var(--text-muted)]">
              PTZ — kamera ulanganda faollashadi
            </p>
          </Panel>

          <Panel className="p-4">
            <Eyebrow>Presetlar</Eyebrow>
            <div className="mt-2 space-y-1">
              {PRESETS.map((p) => (
                <button
                  key={p}
                  onClick={() => sound.play("tick")}
                  className="flex w-full items-center justify-between rounded-[10px] px-3 py-2 text-sm text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]"
                >
                  {p}
                  <ChevronRight size={14} strokeWidth={1.5} className="text-[var(--text-muted)]" />
                </button>
              ))}
            </div>
          </Panel>
        </motion.div>
      </div>
    </div>
  );
}

function PtzBtn({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <button
      aria-label={label}
      onClick={() => sound.play("tick")}
      className="flex aspect-square items-center justify-center rounded-[10px] border border-[var(--border-hairline)] text-[var(--text-secondary)] transition-colors hover:border-[var(--border-active)] hover:text-[var(--text-primary)]"
    >
      {children}
    </button>
  );
}
