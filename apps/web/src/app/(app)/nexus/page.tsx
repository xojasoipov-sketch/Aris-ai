"use client";

/** NEXUS — immersiv boshqaruv sahnasi (Z47).
 *
 * Ega yuborgan referens rasm asosida: markazda ZET yadrosi, atrofida
 * ma'lumot panellari, qo'l bilan boshqaruv va ikki marta qarsakka
 * ovozli javob.
 *
 * IKKI NARSA REFERENSDAN ATAYIN FARQ QILADI:
 *
 *   1. Paneldagi HAMMA son haqiqiy backend'dan keladi. Referensdagi
 *      "12.6K Followers", "+3.45% NVDA", "22° Partly Cloudy" — chiroyli,
 *      lekin ZET ularni o'lchamaydi. Soxta son qo'yish shu loyihada
 *      allaqachon bir marta ega ishonchini yo'qotgan ("ko'p joyi
 *      soxta"), shuning uchun bu yerda faqat ulangan ma'lumot bor.
 *
 *   2. Ranglar ZET tokenlaridan (`--accent-blue`), referensdagi
 *      pushti/binafsha gradient EMAS — dizayn tizimi buni taqiqlaydi.
 *
 * IMKONIYATLAR RUXSATGA BOG'LIQ. Mikrofon va kamera foydalanuvchi
 * bosishi bilan yoqiladi; rad etilsa sahifa ISHLASHDA DAVOM ETADI va
 * nima yo'qligini ochiq yozadi.
 */

import { Hand, Mic, Volume2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { NeuroOrb, type OrbState } from "@/components/core/NeuroOrb";
import { Button, Eyebrow, Panel, StatusDot } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { GREETING, speak, stopSpeaking } from "@/lib/speak";
import { sound } from "@/lib/sound";
import { useClapDetector } from "@/lib/useClapDetector";
import { HAND_CONNECTIONS, useHandTracking } from "@/lib/useHandTracking";
import { useResource } from "@/lib/useResource";

/** Kursor panel ustida deb hisoblanadigan radius (0-1 koordinatada). */
const HOVER_RADIUS = 0.13;

export default function NexusPage() {
  const [orbState, setOrbState] = useState<OrbState>("idle");
  const [caption, setCaption] = useState("");
  const [voiceNote, setVoiceNote] = useState("");
  const [focused, setFocused] = useState<string | null>(null);

  const agents = useResource(() => api.agents(), 20_000);
  const tasks = useResource(() => api.tasks.list(), 20_000);
  const system = useResource(() => api.system(), 5_000);
  const events = useResource(() => api.events.list(), 60_000);

  const hand = useHandTracking();

  const greet = useCallback(() => {
    sound.play("tick");
    setOrbState("speaking");
    setCaption(GREETING);
    void speak(GREETING).then((source) => {
      setVoiceNote(
        source === "server"
          ? ""
          : source === "browser"
            ? "Brauzer ovozi — serverda TTS sozlanmagan"
            : "Ovoz chiqarib bo'lmadi",
      );
      // Javob tugagach yadro tinch holatga qaytadi.
      window.setTimeout(() => setOrbState("idle"), 2600);
    });
  }, []);

  const clap = useClapDetector(greet);

  useEffect(() => () => stopSpeaking(), []);

  /** Panellar — pozitsiya 0-1 koordinatada (qo'l kursori bilan
   * solishtirish uchun ekran o'lchamiga bog'liq bo'lmasin). */
  const panels = useMemo(() => {
    const activeAgents =
      agents.state.kind === "ready"
        ? agents.state.data.filter((a) => a.status === "active").length
        : null;
    const totalAgents = agents.state.kind === "ready" ? agents.state.data.length : null;

    const openTasks =
      tasks.state.kind === "ready"
        ? tasks.state.data.filter((t) => t.status !== "done" && t.status !== "cancelled").length
        : null;

    const nextEvent =
      events.state.kind === "ready"
        ? [...events.state.data]
            .filter((e) => new Date(e.starts_at).getTime() >= Date.now())
            .sort((a, b) => a.starts_at.localeCompare(b.starts_at))[0]
        : undefined;

    const metrics = system.state.kind === "ready" ? system.state.data : null;

    return [
      {
        id: "agents",
        label: "Agentlar",
        value: activeAgents === null ? "—" : `${activeAgents}/${totalAgents}`,
        hint: activeAgents === null ? "aloqa yo'q" : "faol",
        pos: { x: 0.16, y: 0.3 },
      },
      {
        id: "tasks",
        label: "Vazifalar",
        value: openTasks === null ? "—" : String(openTasks),
        hint: openTasks === null ? "aloqa yo'q" : "ochiq",
        pos: { x: 0.16, y: 0.62 },
      },
      {
        id: "cpu",
        label: "CPU",
        value: metrics ? `${metrics.cpu_percent}%` : "—",
        hint: metrics ? `RAM ${metrics.memory_percent}%` : "o'lchanmadi",
        pos: { x: 0.84, y: 0.3 },
      },
      {
        id: "next",
        label: "Keyingi hodisa",
        value: nextEvent
          ? new Date(nextEvent.starts_at).toLocaleTimeString("uz-UZ", {
              hour: "2-digit",
              minute: "2-digit",
            })
          : "—",
        hint: nextEvent ? nextEvent.title : "rejada yo'q",
        pos: { x: 0.84, y: 0.62 },
      },
    ];
  }, [agents.state, tasks.state, system.state, events.state]);

  /** Kursor ostidagi panelni topamiz. */
  useEffect(() => {
    if (!hand.cursor) {
      setFocused(null);
      return;
    }
    const hit = panels.find(
      (p) => Math.hypot(p.pos.x - hand.cursor!.x, p.pos.y - hand.cursor!.y) < HOVER_RADIUS,
    );
    setFocused(hit?.id ?? null);
  }, [hand.cursor, panels]);

  /** Chimdish — fokusdagi panelni "ochish" (hozircha ovozli hisobot). */
  const lastPinchRef = useRef(false);
  useEffect(() => {
    if (hand.pinching && !lastPinchRef.current && focused) {
      const panel = panels.find((p) => p.id === focused);
      if (panel) {
        sound.play("tick");
        const text = `${panel.label}: ${panel.value} ${panel.hint}`;
        setCaption(text);
        setOrbState("speaking");
        void speak(text).then(() => window.setTimeout(() => setOrbState("idle"), 2000));
      }
    }
    lastPinchRef.current = hand.pinching;
  }, [hand.pinching, focused, panels]);

  /** Ochiq kaft — ovozni to'xtatadi ("to'xta" imosi). */
  useEffect(() => {
    if (hand.openPalm) {
      stopSpeaking();
      setOrbState("idle");
    }
  }, [hand.openPalm]);

  return (
    <div className="relative min-h-[calc(100vh-8.5rem)] overflow-hidden px-6 py-6 lg:px-8">
      {/* Kamera oqimi — ko'rinmaydi, faqat model uchun manba. */}
      <video ref={hand.videoRef} playsInline muted className="hidden" />

      <header className="relative z-10 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">Nexus</h1>
          <p className="mt-0.5 text-sm text-[var(--text-secondary)]">
            Qo&apos;l va ovoz bilan boshqaruv
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            onClick={() => void clap.enable()}
            variant={clap.permission === "granted" ? "primary" : "ghost"}
            className="flex items-center gap-2"
            disabled={clap.permission === "granted" || clap.permission === "requesting"}
          >
            <Mic size={15} strokeWidth={1.5} aria-hidden />
            {clap.permission === "granted" ? "Qarsak yoqilgan" : "Qarsakni yoqish"}
          </Button>
          <Button
            onClick={() => void hand.enable()}
            variant={hand.status === "tracking" ? "primary" : "ghost"}
            className="flex items-center gap-2"
            disabled={hand.status === "tracking" || hand.status === "loading"}
          >
            <Hand size={15} strokeWidth={1.5} aria-hidden />
            {hand.status === "tracking"
              ? "Qo'l kuzatilmoqda"
              : hand.status === "loading"
                ? "Model yuklanmoqda…"
                : "Qo'lni yoqish"}
          </Button>
        </div>
      </header>

      {/* Ruxsat/xato holatlari — jimgina ishlamay qolmasin. */}
      <div className="relative z-10 mt-3 space-y-1 text-xs">
        {clap.permission === "denied" ? (
          <p className="text-[var(--status-alert)]">
            Mikrofonga ruxsat berilmadi — qarsak aniqlanmaydi.
          </p>
        ) : null}
        {hand.status === "denied" ? (
          <p className="text-[var(--status-alert)]">
            Kameraga ruxsat berilmadi — qo&apos;l boshqaruvi ishlamaydi.
          </p>
        ) : null}
        {hand.status === "error" ? (
          <p className="text-[var(--status-alert)]">{hand.error}</p>
        ) : null}
        {voiceNote ? <p className="text-[var(--text-muted)]">{voiceNote}</p> : null}
      </div>

      {/* Sahna */}
      <div className="relative mx-auto mt-6 aspect-[4/3] w-full max-w-4xl sm:aspect-[16/9]">
        {/* Markaziy yadro */}
        <button
          onClick={greet}
          aria-label="ZET bilan salomlashish"
          className="absolute top-1/2 left-1/2 h-[38%] w-[38%] -translate-x-1/2 -translate-y-1/2 outline-none"
        >
          <NeuroOrb state={orbState} className="h-full w-full" />
        </button>

        {/* Panellar */}
        {panels.map((panel) => (
          <motion.div
            key={panel.id}
            className="absolute w-[132px] -translate-x-1/2 -translate-y-1/2 sm:w-[160px]"
            style={{ left: `${panel.pos.x * 100}%`, top: `${panel.pos.y * 100}%` }}
            animate={{ scale: focused === panel.id ? 1.05 : 1 }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
          >
            <Panel
              className={`px-3 py-2.5 ${
                focused === panel.id ? "border-[var(--border-active)]" : ""
              }`}
            >
              <Eyebrow>{panel.label}</Eyebrow>
              <div className="data mt-1 text-xl font-semibold text-[var(--text-primary)]">
                {panel.value}
              </div>
              <div className="truncate text-[10px] text-[var(--text-muted)]">{panel.hint}</div>
            </Panel>
          </motion.div>
        ))}

        {/* Qo'l skeleti */}
        {hand.landmarks.length > 0 ? (
          <svg
            className="pointer-events-none absolute inset-0 h-full w-full"
            viewBox="0 0 1 1"
            preserveAspectRatio="none"
            aria-hidden
          >
            {HAND_CONNECTIONS.map(([a, b], i) => {
              const pa = hand.landmarks[a];
              const pb = hand.landmarks[b];
              if (!pa || !pb) return null;
              return (
                <line
                  key={i}
                  x1={pa.x}
                  y1={pa.y}
                  x2={pb.x}
                  y2={pb.y}
                  stroke="var(--accent-blue)"
                  strokeWidth={0.004}
                  opacity={0.6}
                />
              );
            })}
            {hand.landmarks.map((p, i) => (
              <circle key={i} cx={p.x} cy={p.y} r={0.006} fill="var(--accent-glow)" opacity={0.9} />
            ))}
          </svg>
        ) : null}

        {/* Kursor */}
        {hand.cursor ? (
          <motion.div
            className="pointer-events-none absolute h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border"
            style={{
              left: `${hand.cursor.x * 100}%`,
              top: `${hand.cursor.y * 100}%`,
              borderColor: "var(--accent-blue)",
              background: hand.pinching ? "var(--accent-blue)" : "transparent",
            }}
            animate={{ scale: hand.pinching ? 0.7 : 1 }}
            transition={{ type: "spring", stiffness: 400, damping: 25 }}
          />
        ) : null}
      </div>

      {/* Javob matni */}
      <AnimatePresence>
        {caption ? (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            className="relative z-10 mx-auto mt-4 max-w-xl"
          >
            <Panel className="flex items-start gap-2 px-4 py-3">
              <Volume2
                size={15}
                strokeWidth={1.5}
                className="mt-0.5 shrink-0 text-[var(--accent-blue)]"
                aria-hidden
              />
              <p className="text-sm text-[var(--text-primary)]">{caption}</p>
            </Panel>
          </motion.div>
        ) : null}
      </AnimatePresence>

      {/* Imo qo'llanmasi */}
      <div className="relative z-10 mx-auto mt-4 flex max-w-xl flex-wrap justify-center gap-x-4 gap-y-1 text-[10px] text-[var(--text-muted)]">
        <span className="flex items-center gap-1.5">
          <StatusDot
            color={clap.permission === "granted" ? "var(--status-online)" : "var(--status-offline)"}
            pulse={clap.permission === "granted" && clap.level > 0.05}
          />
          ikki marta qarsak — salom
        </span>
        <span>chimdish — panelni o&apos;qish</span>
        <span>ochiq kaft — to&apos;xtat</span>
      </div>
    </div>
  );
}
