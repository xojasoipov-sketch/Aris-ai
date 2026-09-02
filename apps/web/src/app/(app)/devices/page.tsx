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

import { motion } from "motion/react";
import { useEffect, useState } from "react";

import { ConnectionBadge, KillSwitchButton } from "@/components/ui/devices";
import { Button, Panel, Eyebrow } from "@/components/ui/primitives";
import { Tabs } from "@/components/ui/Tabs";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { sound } from "@/lib/sound";

const DISABLED_HINT =
  "Bu amallar ZET o'z Mac/Win kompyuteringizda ishga tushirilganda faollashadi — " +
  "serverda `desktop.*` tool'lari hech qayerga bormaydi.";

/* ── Hotkey builder (docs/11 §2.3) ────────────────────────────── */

const MODIFIERS = ["ctrl", "cmd", "alt", "shift"] as const;

function HotkeyBuilder() {
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
            className={`rounded-full border px-3 py-1 data text-xs transition-colors ${
              mods.includes(m)
                ? "border-[var(--accent-blue)] bg-[rgba(76,141,255,0.15)] text-[var(--accent-blue)]"
                : "border-[var(--border-hairline)] text-[var(--text-secondary)] hover:border-[var(--border-active)]"
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
          className="w-10 rounded-lg border border-[var(--border-hairline)] bg-transparent px-2 py-1 text-center data text-sm outline-none focus:border-[var(--accent-blue)]"
        />
      </div>
      {combo.length > 0 ? (
        <div className="mt-2 data text-xs text-[var(--accent-blue)]">
          Natija: <span className="text-[var(--text-primary)]">{combo.join("+")}</span>
        </div>
      ) : null}
      <Button variant="primary" className="mt-3" disabled title={DISABLED_HINT}>
        Yuborish
      </Button>
    </div>
  );
}

/* ── Kompyuter tab ────────────────────────────────────────────── */

function ComputerTab() {
  const [text, setText] = useState("");
  const [coords, setCoords] = useState<{ x: number; y: number } | null>(null);

  /* SOXTA TASDIQ OQIMI OLIB TASHLANDI (Z48.4).
   *
   * Ilgari "Yuborish" bosilganda tasdiq kartasi chiqardi, tasdiqlangach
   * esa "Amallar tarixi"ga `done` deb YOZILARDI — holbuki hech qanday
   * amal bajarilmagan edi. Server headless, `desktop.*` tool'lari
   * `StubDesktop(available=False)` bilan ishlaydi va hech qayerga
   * bormaydi.
   *
   * Bu soxta tugmadan ham yomonroq: audit jurnali bajarilmagan amalni
   * "bajarildi" deb YOZIB QO'YARDI. Audit yozuvi yolg'on bo'lsa, undan
   * hech qanday foyda qolmaydi.
   *
   * Maydonlar qoldirildi (koordinata, matn, hotkey — ular haqiqiy
   * ma'lumot tayyorlaydi), lekin yuborish O'CHIRILGAN: ZET eganing o'z
   * kompyuterida ishga tushirilib, `desktop.*` haqiqiy provayderga
   * ulanmaguncha bu amallar mumkin emas.
   */

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
      <div className="space-y-6">
        {/* Screen mirror (docs/11 §2.2) */}
        <Panel className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-[var(--border-hairline)] px-4 py-2.5">
            <div className="flex items-center gap-3">
              <Eyebrow>Ekran ko'zgusi</Eyebrow>
              <span className="rounded-full border border-[var(--border-hairline)] px-2 py-0.5 data text-[9px] tracking-widest text-[var(--text-muted)]">
                UNTRUSTED
              </span>
            </div>
            {/* Ilgari bu tugma `sound.play("error")` chalardi va
                BOSHQA HECH NARSA qilmasdi. Ekran ko'zgusi uchun
                manba (`desktop.screenshot`) hali ulanmagan, shuning
                uchun tugma butunlay olib tashlandi — ishlamaydigan
                tugma ishlamasligini bildirgani ma'qul. */}
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
                className="absolute bottom-3 right-3 rounded-lg bg-[var(--bg-elevated)] px-2.5 py-1 data text-xs text-[var(--accent-glow)]"
              >
                x={coords.x} y={coords.y}
              </motion.div>
            ) : null}
          </button>
        </Panel>

        {/* Remote input (docs/11 §2.3) */}
        <div className="grid gap-4 md:grid-cols-3">
          <Panel className="p-4">
            <Eyebrow>Matn yozish</Eyebrow>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={3}
              placeholder="Yoziladigan matn..."
              className="mt-2 w-full resize-none rounded-lg border border-[var(--border-hairline)] bg-transparent p-2.5 text-sm outline-none focus:border-[var(--accent-blue)]"
            />
            <Button variant="primary" className="mt-2" disabled title={DISABLED_HINT}>
              Yuborish
            </Button>
          </Panel>

          <Panel className="p-4">
            <Eyebrow>Tugma bosish</Eyebrow>
            <div className="mt-2">
              <HotkeyBuilder />
            </div>
          </Panel>

          <Panel className="p-4">
            <Eyebrow>Sichqoncha</Eyebrow>
            <div className="mt-2 flex gap-2">
              {(["x", "y"] as const).map((axis) => (
                <label key={axis} className="flex items-center gap-1.5 data text-xs text-[var(--text-muted)]">
                  {axis}=
                  <input
                    type="number"
                    value={coords?.[axis] ?? ""}
                    onChange={(e) =>
                      setCoords((c) => ({ x: c?.x ?? 0, y: c?.y ?? 0, [axis]: Number(e.target.value) }))
                    }
                    className="w-16 rounded-lg border border-[var(--border-hairline)] bg-transparent px-2 py-1 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent-blue)]"
                  />
                </label>
              ))}
            </div>
            <p className="mt-2 text-[11px] text-[var(--text-muted)]">
              Yoki ekran ko'zgusiga bosing — koordinata avtomatik to'ldiriladi
            </p>
            <Button variant="primary" className="mt-2" disabled title={DISABLED_HINT}>
              Yuborish
            </Button>
          </Panel>
        </div>

        {/* Audit jurnali OLIB TASHLANDI: u bajarilmagan amalni
            "bajarildi" deb yozardi. Haqiqiy amallar tarixi ZET run'lari
            orqali backend'da yuritiladi (`audit_log` jadvali). */}
      </div>

      {/* O'ng: tasdiq zonasi haqida HALOL izoh.
          Ilgari bu yerda MAHALLIY tasdiq kartasi chiqardi — hech qanday
          backend tasdig'i emas edi. */}
      <div className="space-y-4">
        <Panel className="p-5">
          <Eyebrow>Tasdiq zonasi</Eyebrow>
          <p className="mt-2 text-xs leading-relaxed text-[var(--text-secondary)]">
            EXECUTE amallar tasdiq talab qiladi (V-32) va tasdiq backend&apos;dagi run
            bilan bog&apos;lanadi — Telegram orqali ham, shu yerda ham bitta xizmatga
            yoziladi.
          </p>
          <p className="mt-2 text-xs leading-relaxed text-[var(--text-muted)]">
            {DISABLED_HINT}
          </p>
        </Panel>
      </div>
    </div>
  );
}

/* ── Telefon tab (docs/11 §3 — Talqin A) ──────────────────────── */

function PhoneTab() {
  /* ILGARI uchta qatorning HAMMASI qotirilgan edi:
   *
   *     ["Bog'langan Telegram", "@ega (owner ID tekshirilgan ✓)"]
   *     ["Ovozli javob", "Yoqilgan (ElevenLabs)"]
   *
   * Ya'ni token umuman sozlanmagan bo'lsa ham "tekshirilgan ✓" va
   * "Yoqilgan" deb turardi. Endi holat `GET /integrations` dan —
   * tekshirilgan sozlamadan. */
  const { state } = useResource(() => api.integrations(), 30_000);
  const rows = state.kind === "ready" ? state.data : [];
  const find = (key: string) => rows.find((r) => r.key === key);

  const telegram = find("telegram");
  const voice = find("elevenlabs");

  return (
    <div className="max-w-md">
      <Panel className="p-6">
        <Eyebrow>Telefon</Eyebrow>
        <div className="mt-4 space-y-3 text-sm">
          {[
            {
              label: "Telegram bot",
              value: telegram?.detail ?? "—",
              ok: telegram?.configured ?? false,
            },
            { label: "Boshqaruv kanali", value: "Telegram bot + Mini App", ok: true },
            {
              label: "Ovozli javob",
              value: voice?.detail ?? "—",
              ok: voice?.configured ?? false,
            },
          ].map(({ label, value, ok }) => (
            <div key={label} className="flex items-baseline justify-between gap-4">
              <span className="text-[var(--text-muted)]">{label}</span>
              <span
                className="text-right"
                style={{ color: ok ? "var(--text-primary)" : "var(--text-muted)" }}
              >
                {state.kind === "loading" ? "tekshirilmoqda…" : value}
              </span>
            </div>
          ))}
        </div>
        <p className="mt-5 border-t border-[var(--border-hairline)] pt-4 text-xs leading-relaxed text-[var(--text-secondary)]">
          Telefon — ZET'ning asosiy boshqaruv paneli. Alohida &quot;masofadan
          boshqarish&quot; funksiyasi yo&apos;q — bu ataylab qilingan dizayn qarori
          (docs/11 §3): shaxsiy telefon ekranini kuzatish maxfiylik jihatidan
          alohida tahlil talab qiladi.
        </p>
      </Panel>
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
            {/* QOTIRILGAN "disconnected" — va bu TO'G'RI. Bu belgi
                backend haqida emas, EGANING KOMPYUTERIDAGI desktop
                agent haqida ("ZET agentni kompyuteringizda ishga
                tushiring"). Bunday agent hali umuman yozilmagan,
                shuning uchun boshqa holat ko'rsatish yolg'on
                bo'lardi. Agent qo'shilganda bu yerga uning haqiqiy
                holati ulanadi. */}
            <ConnectionBadge state="disconnected" />
          </div>
        </div>
        <KillSwitchButton engaged={killswitch} onEngage={engage} onDisengage={disengage} />
      </div>

      {/* Tab pill'lar */}
      <div className="flex">
        <Tabs
          tabs={["computer", "phone"] as const}
          value={tab}
          onChange={setTab}
          labels={{ computer: "Kompyuter", phone: "Telefon" }}
        />
      </div>

      {killswitch ? (
        <Panel className="border-[var(--status-alert)] p-4 text-center">
          <span className="data text-sm font-semibold text-[var(--status-alert)]">
            🔴 KILLSWITCH FAOL — barcha yuborish tugmalari o&apos;chirilgan
          </span>
        </Panel>
      ) : null}

      <div className={killswitch ? "pointer-events-none opacity-40" : ""}>
        {tab === "computer" ? <ComputerTab /> : <PhoneTab />}
      </div>
    </div>
  );
}
