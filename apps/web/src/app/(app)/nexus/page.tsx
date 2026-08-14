"use client";

/** NEXUS — immersiv boshqaruv sahnasi (Z50, referens rasm bo'yicha).
 *
 * TUZILISH ega yuborgan rasmdan AYNAN olingan:
 *
 *     yuqori chap  — NEXUS + tizim holati ustuni
 *     yuqori o'ng  — soat va sana
 *     markaz       — nuqta-bulut yadro, orbitalar bilan
 *     o'rta        — gorizontal karta karuseli, markazdagisi katta
 *     past chap    — tizim jurnali
 *     past markaz  — imo-ishora ro'yxati
 *     past o'ng    — aniqlangan imo va ishonch darajasi
 *
 * BITTA NARSA RASMDAN ATAYIN FARQ QILADI — SONLAR.
 *
 * Rasmda "12.6K Followers +24.6%", "NVDA +3.45%", "22° Partly Cloudy",
 * "FPS 60", "GPU RTX 4080" yozilgan. Ega talabi aniq edi: «men
 * o'yinchoq emas, haqiqiy ishlaydigan tizim yasayapman». Shuning
 * uchun HAR BIR SON o'lchanadigan manbadan keladi:
 *
 *     ob-havo  → Open-Meteo        aksiya   → Yahoo Finance
 *     yangilik → RSS               kurs     → Markaziy bank
 *     sport    → TheSportsDB       tizim    → serverdagi psutil
 *     loyiha/taqvim/agent          → ZET bazasi
 *
 * GPU va TEMP qatorlari OLIB TASHLANDI: brauzer ham, server ham
 * videokarta modeli yoki haroratini o'lchamaydi. "RTX 4080" yozib
 * qo'yish — aynan ega rad etgan soxta ma'lumot. Ularning o'rnida
 * haqiqatan o'lchanadigan CPU/RAM/disk turadi.
 *
 * MUSIQA kartasi ochiq "ulanmagan" holatda: u shaxsiy akkaunt
 * (Spotify) OAuth'ini talab qiladi va kalitsiz haqiqiy manba yo'q.
 */

import { Hand, Mic } from "lucide-react";
import { motion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { NeuroOrb, type OrbState } from "@/components/core/NeuroOrb";
import { CardRail, type RailCard } from "@/components/nexus/CardRail";
import { Sparkline } from "@/components/nexus/Sparkline";
import { SystemLog, useSystemLog } from "@/components/nexus/SystemLog";
import { Button } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { GREETING, speak, stopSpeaking } from "@/lib/speak";
import { sound } from "@/lib/sound";
import { useClapDetector } from "@/lib/useClapDetector";
import { useHandTracking } from "@/lib/useHandTracking";
import { useResource } from "@/lib/useResource";
import { useVoiceInput } from "@/lib/useVoiceInput";

/** Qo'l kursori shuncha siljisa — karusel bitta kartaga suriladi. */
const SWIPE_STEP = 0.16;

/** Rasmning pastki markazidagi imo ro'yxati.
 *
 * `live: false` — imo hali o'qilmaydi. Rasmda oltitasi ham bir xil
 * ko'rinadi, lekin ishlamaydiganini ishlaydigandek ko'rsatish soxta
 * tugma bilan bir narsa. Shuning uchun ular xira chiziladi. */
const GESTURES = [
  { key: "swipe", name: "Surish", hint: "Karta almashtirish", live: true },
  { key: "pinch", name: "Chimdish", hint: "Tanlash", live: true },
  { key: "palm", name: "Ochiq kaft", hint: "To'xtatish", live: true },
  { key: "pull", name: "Tortish", hint: "Kengaytirish", live: false },
  { key: "push", name: "Itarish", hint: "Yig'ish", live: false },
  { key: "circle", name: "Aylana", hint: "AI rejimi", live: false },
] as const;

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-[10px] tracking-wide text-[var(--text-muted)]">{label}</span>
      <span className="data text-[11px] text-[var(--text-primary)]">{value}</span>
    </div>
  );
}

function Clock() {
  const [now, setNow] = useState<Date | null>(null);
  // Server render'da vaqt yo'q — aks holda hidratsiya mos kelmaydi.
  useEffect(() => {
    setNow(new Date());
    const t = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(t);
  }, []);
  if (!now) return null;
  return (
    <div className="text-right">
      <div className="data text-2xl leading-none font-light tracking-tight text-[var(--text-primary)]">
        {now.toLocaleTimeString("uz-UZ", { hour12: false })}
      </div>
      <div className="mt-1 text-[11px] text-[var(--text-secondary)]">
        {now.toLocaleDateString("uz-UZ", { day: "numeric", month: "long", year: "numeric" })}
      </div>
      <div className="text-[10px] text-[var(--text-muted)]">
        {now.toLocaleDateString("uz-UZ", { weekday: "long" })}
      </div>
    </div>
  );
}

export default function NexusPage() {
  const [orbState, setOrbState] = useState<OrbState>("idle");
  const [caption, setCaption] = useState("");
  const [active, setActive] = useState(4);

  const log = useSystemLog();
  const push = log.push;

  const agents = useResource(() => api.agents(), 30_000);
  const tasks = useResource(() => api.tasks.list(), 30_000);
  const projects = useResource(() => api.projects.list(), 60_000);
  const system = useResource(() => api.system(), 5_000);
  const events = useResource(() => api.events.list(), 60_000);
  const feeds = useResource(() => api.feeds(), 120_000);

  const hand = useHandTracking();

  // ── Ovozli buyruq — qarsak → salomlashuv → HAQIQIY /run chaqiruvi ──
  // Web Speech API brauzer ichida matnga aylantiradi, natija esa
  // qotgan javob emas — real Orchestrator'ga (`api.run`) boradi.
  const voice = useVoiceInput((text) => {
    push(`Ovoz: "${text}"`);
    setOrbState("thinking");
    void api.run(text, "web").then((res) => {
      if (res.ok) {
        // Backend'ning HAQIQIY javobi ovozda o'qiladi — qotgan
        // GREETING emas, bu chinakam Jarvis-uslubidagi suhbat.
        setCaption(res.data.message);
        setOrbState("speaking");
        void speak(res.data.message).then(() =>
          window.setTimeout(() => setOrbState("idle"), 2600),
        );
      } else {
        // LLM provayder ishlamasa ham xato JIMGINA yutilmaydi —
        // jurnalda va sahnada ochiq ko'rsatiladi.
        push(`Xato: ${res.error}`);
        setCaption(res.error);
        setOrbState("idle");
      }
    });
  });

  const greet = useCallback(() => {
    sound.play("tick");
    setOrbState("speaking");
    setCaption(GREETING);
    push("Ikki qarsak aniqlandi");
    void speak(GREETING).then(() =>
      window.setTimeout(() => {
        setOrbState("idle");
        // Salomlashuv tugadi — endi ~6 soniya buyruqni tinglaydi
        // (Jarvis-uslub: "qarsak → salom → tingla"). Qo'llab-
        // quvvatlanmasa/ruxsat bo'lmasa buni hook o'zi "unsupported"/
        // "denied" holatiga o'tkazadi — quyidagi effekt buni jurnalga
        // ochiq yozadi.
        voice.start();
        window.setTimeout(() => voice.stop(), 6000);
      }, 2600),
    );
  }, [push, voice.start, voice.stop]);

  const clap = useClapDetector(greet);

  useEffect(() => () => stopSpeaking(), []);

  useEffect(() => {
    if (hand.status === "tracking") push("Qo'l kuzatuvi yoqildi");
    if (hand.status === "error") push(`Kamera xatosi: ${hand.error ?? "noma'lum"}`);
  }, [hand.status, hand.error, push]);

  useEffect(() => {
    if (clap.permission === "granted") push("Mikrofon yoqildi");
  }, [clap.permission, push]);

  useEffect(() => {
    if (voice.permission === "unsupported") push("Ovoz tanish qo'llab-quvvatlanmaydi");
    if (voice.permission === "denied") push("Mikrofonga ruxsat yo'q");
  }, [voice.permission, push]);

  // ── Kartalar (hammasi haqiqiy manbadan) ────────────────────────
  const cards = useMemo<RailCard[]>(() => {
    const f = feeds.state.kind === "ready" ? feeds.state.data : null;
    const dash = (v: string | number | null | undefined) =>
      v === null || v === undefined ? "—" : String(v);

    const metrics = system.state.kind === "ready" ? system.state.data : null;
    const projectList = projects.state.kind === "ready" ? projects.state.data : [];
    const taskList = tasks.state.kind === "ready" ? tasks.state.data : [];
    const agentList = agents.state.kind === "ready" ? agents.state.data : [];
    const upcoming =
      events.state.kind === "ready"
        ? [...events.state.data]
            .filter((e) => new Date(e.starts_at).getTime() >= Date.now())
            .sort((a, b) => a.starts_at.localeCompare(b.starts_at))
            .slice(0, 3)
        : [];

    const big = "data text-[22px] leading-none font-semibold text-[var(--text-primary)]";
    const sub = "mt-1 text-[10px] text-[var(--text-secondary)]";

    const quote = f?.stocks.data?.[0] ?? null;
    const weather = f?.weather.data ?? null;
    const match = f?.sports.data?.[0] ?? null;

    return [
      {
        id: "music",
        title: "MUSIQA",
        subtitle: "Shaxsiy akkaunt kerak",
        body: (
          <p className="text-[10px] leading-relaxed text-[var(--text-muted)]">
            Spotify OAuth orqali ulanadi. Kalitsiz haqiqiy manba yo&apos;q — shuning uchun
            bu yerda son ko&apos;rsatilmaydi.
          </p>
        ),
        footnote: "ulanmagan",
      },
      {
        id: "news",
        title: "YANGILIKLAR",
        subtitle: "O'zbekiston",
        error: f && !f.news.ok ? f.news.error : null,
        body: (
          <ul className="space-y-1.5">
            {(f?.news.data ?? []).slice(0, 4).map((n) => (
              <li
                key={n.link || n.title}
                className="line-clamp-2 text-[10px] leading-snug text-[var(--text-secondary)]"
              >
                {n.title}
              </li>
            ))}
          </ul>
        ),
        footnote: f?.news.source,
      },
      {
        id: "instagram",
        title: "INSTAGRAM",
        subtitle: "Auditoriya tahlili",
        body: (
          <p className="text-[10px] leading-relaxed text-[var(--text-muted)]">
            Sozlamalarda Instagram tokeni berilsa, obunachilar va qamrov shu yerda
            ko&apos;rinadi.
          </p>
        ),
        footnote: "token kerak",
      },
      {
        id: "stocks",
        title: "BIRJA",
        subtitle: quote ? quote.name : "Bozor ma'lumoti",
        error: f && !f.stocks.ok ? f.stocks.error : null,
        body: quote ? (
          <div>
            <div
              className="data text-[19px] leading-none font-semibold"
              style={{
                color:
                  quote.change_percent >= 0 ? "var(--status-online)" : "var(--status-alert)",
              }}
            >
              {quote.change_percent >= 0 ? "+" : ""}
              {quote.change_percent}%
            </div>
            <div className={sub}>
              {quote.price} {quote.currency}
            </div>
            <div className="mt-2">
              <Sparkline values={quote.spark} positive={quote.change_percent >= 0} />
            </div>
          </div>
        ) : null,
        footnote: quote ? quote.symbol : undefined,
      },
      {
        id: "ai",
        title: "ZET",
        subtitle: "Shaxsiy yordamchi",
        body: (
          <div className="flex h-full flex-col justify-between">
            <div>
              <div className={big}>{dash(agentList.filter((a) => a.status === "active").length)}</div>
              <div className={sub}>faol agent</div>
            </div>
            <p className="text-[10px] leading-snug text-[var(--text-secondary)]">
              {caption || "Ikki marta qarsak chaling"}
            </p>
          </div>
        ),
        footnote: "yadro",
      },
      {
        id: "projects",
        title: "LOYIHALAR",
        subtitle: "Bajarilish holati",
        body: (
          <div>
            <div className={big}>{projectList.length || "—"}</div>
            <div className={sub}>
              {projectList.length ? `${taskList.length} vazifa` : "hali loyiha yo'q"}
            </div>
            <ul className="mt-2.5 space-y-1.5">
              {projectList.slice(0, 3).map((p) => (
                <li key={p.id}>
                  <div className="truncate text-[10px] text-[var(--text-secondary)]">
                    {p.name}
                  </div>
                  <div className="mt-1 h-[3px] overflow-hidden rounded-full bg-[var(--surface-hover)]">
                    <div
                      className="h-full rounded-full bg-[var(--accent-blue)]"
                      style={{ width: `${p.progress}%` }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ),
      },
      {
        id: "calendar",
        title: "TAQVIM",
        subtitle: "Kelgusi hodisalar",
        body: upcoming.length ? (
          <ul className="space-y-2">
            {upcoming.map((e) => (
              <li key={e.id} className="flex gap-2">
                <span className="data shrink-0 text-[10px] text-[var(--accent-blue)]">
                  {new Date(e.starts_at).toLocaleTimeString("uz-UZ", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
                <span className="line-clamp-2 text-[10px] leading-snug text-[var(--text-secondary)]">
                  {e.title}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[10px] text-[var(--text-muted)]">Rejada hodisa yo&apos;q</p>
        ),
      },
      {
        id: "weather",
        title: "OB-HAVO",
        subtitle: "Toshkent",
        error: f && !f.weather.ok ? f.weather.error : null,
        body: weather ? (
          <div>
            <div className="data text-[30px] leading-none font-light text-[var(--text-primary)]">
              {weather.temperature_c}°
            </div>
            <div className={sub}>{weather.condition}</div>
            <div className="data mt-2 text-[10px] text-[var(--text-muted)]">
              Y:{weather.high_c}° P:{weather.low_c}° · namlik {weather.humidity_percent}%
            </div>
          </div>
        ) : null,
        footnote: f?.weather.source,
      },
      {
        id: "rates",
        title: "VALYUTA",
        subtitle: "Markaziy bank kursi",
        error: f && !f.rates.ok ? f.rates.error : null,
        body: (
          <ul className="space-y-2">
            {(f?.rates.data ?? []).map((r) => (
              <li key={r.code} className="flex items-baseline justify-between gap-2">
                <span className="data text-[11px] text-[var(--text-secondary)]">{r.code}</span>
                <span className="data text-[12px] text-[var(--text-primary)]">
                  {r.rate.toLocaleString("uz-UZ", { maximumFractionDigits: 0 })}
                </span>
              </li>
            ))}
          </ul>
        ),
        footnote: "so'm",
      },
      {
        id: "sports",
        title: "SPORT",
        subtitle: match ? match.league : "Oxirgi natijalar",
        error: f && !f.sports.ok ? f.sports.error : null,
        body: match ? (
          <div>
            <div className="text-[10px] text-[var(--text-secondary)]">{match.home}</div>
            <div className="data my-1 text-[20px] leading-none font-semibold text-[var(--text-primary)]">
              {match.home_score} : {match.away_score}
            </div>
            <div className="text-[10px] text-[var(--text-secondary)]">{match.away}</div>
            <div className="data mt-2 text-[9px] text-[var(--text-muted)]">{match.date}</div>
          </div>
        ) : null,
        footnote: f?.sports.source,
      },
      {
        id: "system",
        title: "TIZIM",
        subtitle: "Server holati",
        body: metrics ? (
          <div className="space-y-2">
            <div>
              <div className={big}>{metrics.cpu_percent}%</div>
              <div className={sub}>protsessor</div>
            </div>
            <Row label="RAM" value={`${metrics.memory_percent}%`} />
            <Row label="DISK" value={`${metrics.disk_percent}%`} />
          </div>
        ) : (
          <p className="text-[10px] text-[var(--text-muted)]">O&apos;lchanmadi</p>
        ),
      },
    ];
  }, [feeds.state, system.state, projects.state, tasks.state, agents.state, events.state, caption]);

  // ── Qo'l bilan surish (SWIPE) ──────────────────────────────────
  const anchorRef = useRef<number | null>(null);
  useEffect(() => {
    if (!hand.cursor) {
      anchorRef.current = null;
      return;
    }
    if (anchorRef.current === null) {
      anchorRef.current = hand.cursor.x;
      return;
    }
    const delta = hand.cursor.x - anchorRef.current;
    if (Math.abs(delta) >= SWIPE_STEP) {
      // Qo'l o'ngga siljisa karusel chapga suriladi — jismoniy
      // kartani surish hissi shunday.
      setActive((cur) => {
        const next = Math.min(Math.max(cur + (delta > 0 ? 1 : -1), 0), cards.length - 1);
        if (next !== cur) sound.play("tick");
        return next;
      });
      anchorRef.current = hand.cursor.x;
    }
  }, [hand.cursor, cards.length]);

  // ── Chimdish — kartani ovoz bilan o'qish ───────────────────────
  const lastPinch = useRef(false);
  useEffect(() => {
    if (hand.pinching && !lastPinch.current) {
      const card = cards[active];
      if (card) {
        sound.play("tick");
        push(`Tanlandi: ${card.title}`);
        setOrbState("speaking");
        void speak(`${card.title}. ${card.subtitle}`).then(() =>
          window.setTimeout(() => setOrbState("idle"), 1800),
        );
      }
    }
    lastPinch.current = hand.pinching;
  }, [hand.pinching, active, cards, push]);

  useEffect(() => {
    if (hand.openPalm) {
      stopSpeaking();
      setOrbState("idle");
    }
  }, [hand.openPalm]);

  const metrics = system.state.kind === "ready" ? system.state.data : null;
  const online = system.state.kind === "ready";
  const gesture = hand.pinching
    ? "Chimdish"
    : hand.openPalm
      ? "Ochiq kaft"
      : hand.cursor
        ? "Qo'l aniqlandi"
        : "—";

  return (
    <div className="relative min-h-[calc(100vh-8.5rem)] overflow-hidden">
      <video ref={hand.videoRef} playsInline muted className="hidden" />

      {/* Markazdagi yadro — kartalar ORTIDA */}
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
        <div className="h-[34rem] w-[34rem] max-w-[92vw] opacity-70">
          <NeuroOrb state={orbState} />
        </div>
      </div>

      <div className="relative z-10 flex min-h-[calc(100vh-8.5rem)] flex-col px-5 py-5 lg:px-7">
        {/* ── Yuqori qator ── */}
        <div className="flex items-start justify-between gap-6">
          <div className="w-[13rem]">
            <div className="flex items-baseline gap-2">
              <span className="text-[15px] font-semibold tracking-[0.18em] text-[var(--text-primary)]">
                NEXUS
              </span>
              <span className="data text-[9px] text-[var(--text-muted)]">ZET</span>
            </div>
            <div className="eyebrow mt-3 mb-1.5">Tizim holati</div>
            <div className="space-y-1">
              <div className="flex items-center gap-1.5">
                <span
                  className="inline-block h-1.5 w-1.5 rounded-full"
                  style={{
                    background: online ? "var(--status-online)" : "var(--status-offline)",
                  }}
                />
                <span className="text-[11px] text-[var(--text-primary)]">
                  {online ? "ONLAYN" : "ALOQA YO'Q"}
                </span>
              </div>
              <Row label="PROTSESSOR" value={metrics ? `${metrics.cpu_percent}%` : "—"} />
              <Row label="XOTIRA" value={metrics ? `${metrics.memory_percent}%` : "—"} />
              <Row label="DISK" value={metrics ? `${metrics.disk_percent}%` : "—"} />
              <Row
                label="ISHLASH VAQTI"
                value={
                  metrics ? `${Math.floor(metrics.uptime_seconds / 3600)} soat` : "—"
                }
              />
              <Row
                label="QO'L KUZATUVI"
                value={hand.status === "tracking" ? "FAOL" : "O'CHIQ"}
              />
            </div>
          </div>

          <Clock />
        </div>

        {/* ── Karusel ── */}
        <div className="flex flex-1 items-center justify-center">
          <CardRail cards={cards} active={active} onActiveChange={setActive} />
        </div>

        {/* ── Pastki qator ── */}
        <div className="flex flex-wrap items-end justify-between gap-4">
          <SystemLog lines={log.lines} />

          <div className="flex flex-col items-center gap-3">
            <div className="flex flex-wrap justify-center gap-2">
              <Button
                onClick={() => void clap.enable()}
                variant={clap.permission === "granted" ? "primary" : "ghost"}
                className="flex items-center gap-2 text-xs"
                disabled={clap.permission === "granted" || clap.permission === "requesting"}
              >
                <Mic size={14} strokeWidth={1.5} aria-hidden />
                {clap.permission === "granted" ? "Qarsak yoqilgan" : "Qarsakni yoqish"}
              </Button>
              <Button
                onClick={() => void hand.enable()}
                variant={hand.status === "tracking" ? "primary" : "ghost"}
                className="flex items-center gap-2 text-xs"
                disabled={hand.status === "tracking" || hand.status === "loading"}
              >
                <Hand size={14} strokeWidth={1.5} aria-hidden />
                {hand.status === "tracking" ? "Qo'l yoqilgan" : "Qo'lni yoqish"}
              </Button>
            </div>

            <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2 rounded-[14px] border border-[var(--border-hairline)] bg-[rgba(11,14,20,0.6)] px-4 py-2.5">
              {GESTURES.map((g) => (
                <div
                  key={g.key}
                  className="flex flex-col items-center"
                  style={{ opacity: g.live ? 1 : 0.35 }}
                  title={g.live ? g.hint : "Hali ulanmagan"}
                >
                  <span className="text-[10px] font-medium text-[var(--text-primary)]">
                    {g.name}
                  </span>
                  <span className="text-[9px] text-[var(--text-muted)]">{g.hint}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="w-[13rem] rounded-[12px] border border-[var(--border-hairline)] bg-[rgba(11,14,20,0.6)] px-3 py-2.5">
            <div className="eyebrow mb-1.5">Imo-ishora</div>
            <div className="text-[13px] text-[var(--text-primary)]">{gesture}</div>
            {/* Ishonch foizi rasmda bor, lekin MediaPipe bu yerda uni
                bermaydi — o'ylab topilgan 98% yozilmaydi. */}
            <div className="mt-1.5 text-[10px] text-[var(--text-muted)]">
              {hand.status === "tracking"
                ? `${hand.landmarks.length} nuqta o'qilmoqda`
                : "Kamera o'chiq"}
            </div>
            {voice.permission === "listening" ? (
              <div className="mt-1 text-[10px] text-[var(--accent-blue)]">
                Tinglanmoqda…
              </div>
            ) : null}
          </div>
        </div>
      </div>

      {caption ? (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="pointer-events-none absolute inset-x-0 bottom-[7.5rem] z-20 flex justify-center"
        >
          <span className="rounded-full border border-[var(--border-hairline)] bg-[rgba(11,14,20,0.85)] px-4 py-1.5 text-xs text-[var(--text-primary)]">
            {caption}
          </span>
        </motion.div>
      ) : null}
    </div>
  );
}
