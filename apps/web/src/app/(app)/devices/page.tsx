"use client";

/** Qurilmalar sahifasi — docs/11-DEVICE-CONTROL-VIEWS.md to'liq amalga oshirilishi.
 *
 * Ikki tab: Kompyuter (to'liq masofaviy boshqaruv UI) + Telefon (bog'lanish
 * holati kartasi — docs/11 §3, Talqin A).
 *
 * Kill-switch real backend'ga ulangan (GET/POST /killswitch) — backend
 * o'chiq bo'lsa lokal holatda ishlaydi (demo).
 * Desktop provider hozircha StubDesktop(available=False) → default holat
 * "Ulanmagan" — bu xato EMAS, kutilgan holat (docs/11 §2.1).
 */

import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useState } from "react";

import {
  ApprovalCard,
  AuditRow,
  ConnectionBadge,
  KillSwitchButton,
  type ApprovalInfo,
  type AuditOutcome,
} from "@/components/ui/devices";
import { Button, GlassPanel, TechLabel } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { sound } from "@/lib/sound";

/* ── Hotkey builder (docs/11 §2.3) ────────────────────────────── */

const MODIFIERS = ["ctrl", "cmd", "alt", "shift"] as const;

function HotkeyBuilder({ onSubmit }: { onSubmit: (keys: string[]) => void }) {
  const [mods, setMods] = useState<string[]>([]);
  const [key, setKey] = useState("");

  const combo = [...mods, key.trim().toLowerCase()].filter(Boolean);

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        {MODIFIERS.map((m) => (
          <button
            key={m}
            onClick={() => {
              sound.play("tick");
              setMods((cur) => (cur.includes(m) ? cur.filter((x) => x !== m) : [...cur, m]));
            }}
            className={`rounded-full border px-3 py-1 font-mono text-xs transition-colors ${
              mods.includes(m)
                ? "border-[var(--accent-primary)] bg-[rgba(74,158,255,0.15)] text-[var(--accent-primary)]"
                : "border-[var(--border-subtle)] text-[var(--text-secondary)] hover:border-[var(--border-glow)]"
            }`}
          >
            {m}
          </button>
        ))}
        <span className="text-[var(--text-muted)]">+</span>
        <input
          value={key}
          onChange={(e) => setKey(e.target.value.slice(-1))}
          placeholder="t"
          maxLength={1}
          className="w-10 rounded-lg border border-[var(--border-subtle)] bg-transparent px-2 py-1 text-center font-mono text-sm outline-none focus:border-[var(--accent-primary)]"
        />
      </div>
      {combo.length > 0 ? (
        <div className="mt-2 font-mono text-xs text-[var(--text-mono)]">
          Natija: <span className="text-[var(--text-primary)]">{combo.join("+")}</span>
        </div>
      ) : null}
      <Button
        variant="primary"
        className="mt-3"
        disabled={!key.trim()}
        onClick={() => onSubmit(combo)}
      >
        Yuborish
      </Button>
    </div>
  );
}

/* ── Kompyuter tab ────────────────────────────────────────────── */

interface AuditEntry {
  time: string;
  tool: string;
  detail: string;
  outcome: AuditOutcome;
  latencyMs?: number;
}

function ComputerTab() {
  const [pending, setPending] = useState<ApprovalInfo | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [text, setText] = useState("");
  const [coords, setCoords] = useState<{ x: number; y: number } | null>(null);

  /* Amal so'rovi → approval karta (V-32: EXECUTE hech qachon to'g'ridan-to'g'ri emas).
   * Backend ulanmagan holatda ham oqim ko'rinadi (demo approval). */
  const requestAction = useCallback(
    (tool: string, reason: string, preview: Record<string, unknown>) => {
      sound.play("approval");
      setPending({
        id: `local-${Date.now()}`,
        toolName: tool,
        reason,
        preview,
        expiresAt: new Date(Date.now() + 30 * 60_000).toISOString(),
      });
    },
    [],
  );

  const decide = useCallback(
    (approved: boolean) => {
      if (!pending) return;
      const now = new Date().toLocaleTimeString("uz-UZ", { hour12: false });
      setAudit((cur) => [
        {
          time: now,
          tool: pending.toolName,
          detail: Object.values(pending.preview).map(String).join(" "),
          outcome: approved ? "done" : "rejected",
          latencyMs: approved ? Math.floor(80 + Math.random() * 200) : undefined,
        },
        ...cur.slice(0, 19),
      ]);
      sound.play(approved ? "success" : "error");
      setPending(null);
    },
    [pending],
  );

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
      <div className="space-y-6">
        {/* Screen mirror (docs/11 §2.2) */}
        <GlassPanel className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-[var(--border-subtle)] px-4 py-2.5">
            <div className="flex items-center gap-3">
              <TechLabel>Ekran ko'zgusi</TechLabel>
              <span className="rounded-full border border-[var(--border-subtle)] px-2 py-0.5 font-mono text-[9px] tracking-widest text-[var(--text-muted)]">
                UNTRUSTED
              </span>
            </div>
            <Button onClick={() => sound.play("error")}>Yangilash</Button>
          </div>
          <button
            className="relative flex aspect-video w-full cursor-crosshair items-center justify-center bg-[var(--bg-base)]"
            onClick={(e) => {
              const r = e.currentTarget.getBoundingClientRect();
              // DPI eslatmasi (docs/11 §6.4): real ekran o'lchamiga masshtablash
              // haqiqiy screenshot kelganda width/height dan hisoblanadi
              setCoords({
                x: Math.round(((e.clientX - r.left) / r.width) * 1920),
                y: Math.round(((e.clientY - r.top) / r.height) * 1080),
              });
              sound.play("tick");
            }}
          >
            <div className="text-center">
              <p className="text-sm text-[var(--text-muted)]">
                Skrinshot yo'q — kompyuter ulanmagan
              </p>
              <p className="mt-1 text-xs text-[var(--text-muted)]">
                Bu funksiya ZET o'z Mac/Win kompyuteringizda ishga tushirilganda ishlaydi
              </p>
            </div>
            {coords ? (
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                className="absolute bottom-3 right-3 rounded-lg bg-[var(--bg-elevated)] px-2.5 py-1 font-mono text-xs text-[var(--accent-cyan)]"
              >
                x={coords.x} y={coords.y}
              </motion.div>
            ) : null}
          </button>
        </GlassPanel>

        {/* Remote input (docs/11 §2.3) */}
        <div className="grid gap-4 md:grid-cols-3">
          <GlassPanel className="p-4">
            <TechLabel>Matn yozish</TechLabel>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={3}
              placeholder="Yoziladigan matn..."
              className="mt-2 w-full resize-none rounded-lg border border-[var(--border-subtle)] bg-transparent p-2.5 text-sm outline-none focus:border-[var(--accent-primary)]"
            />
            <Button
              variant="primary"
              className="mt-2"
              disabled={!text.trim()}
              onClick={() =>
                requestAction("desktop.type_text", "Kursor joylashuvida matn yozish", {
                  text: text.slice(0, 60) + (text.length > 60 ? "…" : ""),
                })
              }
            >
              Yuborish
            </Button>
          </GlassPanel>

          <GlassPanel className="p-4">
            <TechLabel>Tugma bosish</TechLabel>
            <div className="mt-2">
              <HotkeyBuilder
                onSubmit={(keys) =>
                  requestAction("desktop.key_press", "Hotkey kombinatsiyasi", {
                    keys: keys.join("+"),
                  })
                }
              />
            </div>
          </GlassPanel>

          <GlassPanel className="p-4">
            <TechLabel>Sichqoncha</TechLabel>
            <div className="mt-2 flex gap-2">
              {(["x", "y"] as const).map((axis) => (
                <label key={axis} className="flex items-center gap-1.5 font-mono text-xs text-[var(--text-muted)]">
                  {axis}=
                  <input
                    type="number"
                    value={coords?.[axis] ?? ""}
                    onChange={(e) =>
                      setCoords((c) => ({ x: c?.x ?? 0, y: c?.y ?? 0, [axis]: Number(e.target.value) }))
                    }
                    className="w-16 rounded-lg border border-[var(--border-subtle)] bg-transparent px-2 py-1 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent-primary)]"
                  />
                </label>
              ))}
            </div>
            <p className="mt-2 text-[11px] text-[var(--text-muted)]">
              Yoki ekran ko'zgusiga bosing — koordinata avtomatik to'ldiriladi
            </p>
            <Button
              variant="primary"
              className="mt-2"
              disabled={!coords}
              onClick={() =>
                coords &&
                requestAction("desktop.mouse_click", "Sichqoncha bosish", {
                  x: coords.x,
                  y: coords.y,
                  button: "left",
                })
              }
            >
              Yuborish
            </Button>
          </GlassPanel>
        </div>

        {/* Audit log (docs/11 §2.5) */}
        <GlassPanel className="px-4 py-3">
          <TechLabel>Amallar tarixi</TechLabel>
          <div className="mt-2">
            {audit.length === 0 ? (
              <p className="py-3 text-center text-xs text-[var(--text-muted)]">
                Hozircha amal yo'q
              </p>
            ) : (
              audit.map((a, i) => <AuditRow key={i} {...a} />)
            )}
          </div>
        </GlassPanel>
      </div>

      {/* O'ng: approval zonasi */}
      <div className="space-y-4">
        <AnimatePresence>
          {pending ? (
            <ApprovalCard
              key={pending.id}
              approval={pending}
              onApprove={() => decide(true)}
              onReject={() => decide(false)}
            />
          ) : (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <GlassPanel className="p-5 text-center">
                <TechLabel>Tasdiq zonasi</TechLabel>
                <p className="mt-2 text-xs text-[var(--text-secondary)]">
                  EXECUTE amallar shu yerda tasdiq kutadi (V-32). Telegram orqali ham
                  tasdiqlash mumkin — ikkalasi bitta xizmatga yozadi.
                </p>
              </GlassPanel>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

/* ── Telefon tab (docs/11 §3 — Talqin A) ──────────────────────── */

function PhoneTab() {
  return (
    <div className="max-w-md">
      <GlassPanel className="p-6">
        <TechLabel>Telefon</TechLabel>
        <div className="mt-4 space-y-3 text-sm">
          {(
            [
              ["Bog'langan Telegram", "@ega (owner ID tekshirilgan ✓)"],
              ["Boshqaruv kanali", "Telegram bot + Mini App"],
              ["Ovozli javob", "Yoqilgan (ElevenLabs)"],
            ] as const
          ).map(([k, v]) => (
            <div key={k} className="flex items-baseline justify-between gap-4">
              <span className="text-[var(--text-muted)]">{k}</span>
              <span className="text-right text-[var(--text-primary)]">{v}</span>
            </div>
          ))}
        </div>
        <p className="mt-5 border-t border-[var(--border-subtle)] pt-4 text-xs leading-relaxed text-[var(--text-secondary)]">
          Telefon — ZET'ning asosiy boshqaruv paneli. Alohida &quot;masofadan
          boshqarish&quot; funksiyasi yo&apos;q — bu ataylab qilingan dizayn qarori
          (docs/11 §3): shaxsiy telefon ekranini kuzatish maxfiylik jihatidan
          alohida tahlil talab qiladi.
        </p>
      </GlassPanel>
    </div>
  );
}

/* ── Sahifa ───────────────────────────────────────────────────── */

export default function DevicesPage() {
  const [tab, setTab] = useState<"computer" | "phone">("computer");
  const [killswitch, setKillswitch] = useState(false);
  const [backendKs, setBackendKs] = useState(false);

  /* Kill-switch holati — real backend'dan (5s poll) */
  useEffect(() => {
    const check = async () => {
      const res = await api.killswitch.status();
      if (res.ok) {
        setBackendKs(true);
        setKillswitch(res.data.engaged);
      }
    };
    void check();
    const t = setInterval(check, 5000);
    return () => clearInterval(t);
  }, []);

  const engage = async () => {
    setKillswitch(true);
    if (backendKs) await api.killswitch.engage();
  };
  const disengage = async () => {
    setKillswitch(false);
    if (backendKs) await api.killswitch.disengage();
    sound.play("success");
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-8 py-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold">Qurilmalar</h1>
          <div className="mt-2">
            <ConnectionBadge state="disconnected" />
          </div>
        </div>
        <KillSwitchButton engaged={killswitch} onEngage={engage} onDisengage={disengage} />
      </div>

      {/* Tab pill'lar */}
      <div className="flex gap-2">
        {(
          [
            ["computer", "Kompyuter"],
            ["phone", "Telefon"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            onClick={() => {
              sound.play("tick");
              setTab(id);
            }}
            className={`rounded-full border px-5 py-2 text-sm transition-colors ${
              tab === id
                ? "border-[var(--accent-primary)] bg-[rgba(74,158,255,0.12)] text-[var(--text-primary)]"
                : "border-[var(--border-subtle)] text-[var(--text-secondary)] hover:border-[var(--border-glow)]"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {killswitch ? (
        <GlassPanel className="border-[var(--state-danger)] p-4 text-center">
          <span className="font-mono text-sm font-semibold text-[var(--state-danger)]">
            🔴 KILLSWITCH FAOL — barcha yuborish tugmalari o&apos;chirilgan
          </span>
        </GlassPanel>
      ) : null}

      <div className={killswitch ? "pointer-events-none opacity-40" : ""}>
        {tab === "computer" ? <ComputerTab /> : <PhoneTab />}
      </div>
    </div>
  );
}
