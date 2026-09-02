"use client";

/** Sozlamalar (/settings) — TEKSHIRILGAN holat bilan (Z46.2).
 *
 * ILGARI NIMA BO'LGAN. Integratsiya holati sahifa faylida QO'LDA
 * yozilgan massiv edi va har bir yozuvda `configured` bayrog'i
 * qo'lda `true`/`false` qilib qo'yilgandi. Ya'ni sahifa "Telegram
 * bot — Sozlangan" deb ko'rsatardi, hech qanday tekshiruvsiz: kalit
 * o'chirilgan bo'lsa ham xuddi shu yozuv chiqaverardi.
 *
 * Endi `GET /integrations` orqali `.env`dagi HAQIQIY holat keladi.
 * Sirning O'ZI baribir chiqmaydi — faqat bor/yo'qligi va sababi.
 *
 * Ikkita o'lik toggle ("Tungi rejim", "Bildirishnomalar") olib
 * tashlandi: ular holatga yozardi-yu, qiymat HECH QAYERDA o'qilmasdi
 * — bosish hech narsani o'zgartirmasdi.
 */

import { Upload } from "lucide-react";
import { motion } from "motion/react";
import { useRef, useState } from "react";

import { SettingsRow as Row, Toggle } from "@/components/ui/forms";
import { Button, Eyebrow, Panel, StatusDot } from "@/components/ui/primitives";
import { api, type ProfileIngestResultDto } from "@/lib/api";
import { sound } from "@/lib/sound";
import { useResource } from "@/lib/useResource";

/* Accent variantlari — master tizim default: #4C8DFF */
const ACCENTS = ["#4C8DFF", "#22C55E", "#F59E0B", "#EC4899", "#A78BFA", "#EF4444"] as const;

/** Profil fayl yuklash holati — idle -> yuklanmoqda -> natija/xato.
 *
 * MUHIM: bu QO'LDA, BIR MARTALIK fayl yuklash — ega o'zi fayl tanlaydi va
 * o'zi "Yuklash"ni bosadi. Bu YANGI DOIMIY/AVTOMATIK eslovchi tizim EMAS
 * (loyihada ambient/wearable doimiy tinglash qo'shilmagan va qo'shilmaydi).
 */
type ProfileIngestState =
  | { kind: "idle" }
  | { kind: "yuklanmoqda" }
  | { kind: "success"; data: ProfileIngestResultDto }
  | { kind: "error"; message: string };

export default function SettingsPage() {
  const [accent, setAccent] = useState<string>(ACCENTS[0]);
  const [soundOn, setSoundOn] = useState(true);
  const integrations = useResource(() => api.integrations(), 30_000);

  const [profileFile, setProfileFile] = useState<File | null>(null);
  const [ingestState, setIngestState] = useState<ProfileIngestState>({ kind: "idle" });
  const fileInputRef = useRef<HTMLInputElement>(null);

  const applyAccent = (c: string) => {
    setAccent(c);
    document.documentElement.style.setProperty("--accent-blue", c);
    sound.play("tick");
  };

  const uploadProfile = async () => {
    if (!profileFile) return;
    setIngestState({ kind: "yuklanmoqda" });
    const res = await api.memory.ingestProfile(profileFile);
    setIngestState(
      res.ok ? { kind: "success", data: res.data } : { kind: "error", message: res.error },
    );
  };

  return (
    <div className="mx-auto max-w-3xl space-y-5 px-6 py-6 lg:px-8">
      <h1 className="text-xl font-semibold">Sozlamalar</h1>

      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, ease: "easeOut" }} className="space-y-4">
        {/* Ko'rinish */}
        <Panel className="px-5 py-4">
          <Eyebrow>Ko'rinish</Eyebrow>
          <div className="mt-2">
            <Row label="Akцent rang">
              <div className="flex gap-2">
                {ACCENTS.map((c) => (
                  <button
                    key={c}
                    aria-label={`Akцent ${c}`}
                    onClick={() => applyAccent(c)}
                    className="h-6 w-6 rounded-full transition-transform hover:scale-110"
                    style={{
                      background: c,
                      outline: accent === c ? `2px solid ${c}` : "none",
                      outlineOffset: 2,
                    }}
                  />
                ))}
              </div>
            </Row>
            <Row label="UI zichligi">
              <span className="text-sm text-[var(--text-secondary)]">Qulay</span>
            </Row>
          </div>
        </Panel>

        {/* Umumiy */}
        <Panel className="px-5 py-4">
          <Eyebrow>Umumiy</Eyebrow>
          <div className="mt-2">
            <Row label="Interfeys tovushlari">
              <Toggle
                on={soundOn}
                onChange={(v) => {
                  setSoundOn(v);
                  sound.setEnabled(v);
                }}
              />
            </Row>
            <Row label="Til">
              <span className="text-sm text-[var(--text-secondary)]">O'zbekcha</span>
            </Row>
            <Row label="Vaqt mintaqasi">
              <span className="data text-sm text-[var(--text-secondary)]">(UTC+5) Toshkent</span>
            </Row>
          </div>
        </Panel>

        {/* Integratsiyalar — faqat holat, sir YO'Q */}
        <Panel className="px-5 py-4">
          <div className="flex items-baseline justify-between">
            <Eyebrow>Integratsiyalar</Eyebrow>
            <span className="text-[10px] text-[var(--text-muted)]">
              Kalitlar faqat serverdagi .env faylida
            </span>
          </div>
          <div className="mt-2">
            {integrations.state.kind === "loading" ? (
              <p className="py-3 text-xs text-[var(--text-muted)]">Tekshirilmoqda…</p>
            ) : null}
            {integrations.state.kind === "error" ? (
              <p className="py-3 text-xs text-[var(--status-alert)]">
                Holatni o&apos;qib bo&apos;lmadi: {integrations.state.message}
              </p>
            ) : null}
            {integrations.state.kind === "ready"
              ? integrations.state.data.map((i) => (
                  <Row key={i.key} label={i.label}>
                    <div className="flex items-center gap-2">
                      <StatusDot
                        color={i.configured ? "var(--status-online)" : "var(--status-offline)"}
                      />
                      <span
                        className="text-xs"
                        style={{
                          color: i.configured ? "var(--status-online)" : "var(--text-muted)",
                        }}
                        title={i.detail}
                      >
                        {i.configured ? "Sozlangan" : i.detail || "Sozlanmagan"}
                      </span>
                    </div>
                  </Row>
                ))
              : null}
          </div>
        </Panel>

        {/* Xavfsizlik */}
        <Panel className="px-5 py-4">
          <Eyebrow>Xavfsizlik</Eyebrow>
          <div className="mt-2">
            <Row label="EXECUTE amallar uchun tasdiq (V-32)">
              <span className="text-xs text-[var(--status-online)]">Majburiy — o'chirib bo'lmaydi</span>
            </Row>
            <Row label="Tasdiq muddati (TTL)">
              <span className="data text-sm text-[var(--text-secondary)]">30 daqiqa</span>
            </Row>
            <Row label="Owner allowlist">
              <span className="text-xs text-[var(--status-online)]">Faol</span>
            </Row>
          </div>
        </Panel>

        {/* Xotira / Profil — QO'LDA, bir martalik fayl yuklash.
            Doimiy/avtomatik eslovchi tizim EMAS. */}
        <Panel className="px-5 py-4">
          <Eyebrow>Xotira / Profil</Eyebrow>
          <p className="mt-2 text-xs leading-relaxed text-[var(--text-secondary)]">
            Markdown profil faylini (masalan <code>BOSS_PROFILE.md</code>) yuklang — ZET uni
            bo&apos;limlarga bo&apos;lib xotirasiga saqlaydi. Bu qo&apos;lda, bir martalik fayl
            yuklash — doimiy yoki avtomatik eslovchi tizim emas.
          </p>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept=".md,text/markdown"
              onChange={(e) => {
                setProfileFile(e.target.files?.[0] ?? null);
                setIngestState({ kind: "idle" });
              }}
              className="hidden"
            />
            <Button
              variant="ghost"
              onClick={() => fileInputRef.current?.click()}
              aria-label="Profil faylini tanlash"
            >
              <span className="flex items-center gap-1.5">
                <Upload size={15} strokeWidth={1.5} aria-hidden />
                Fayl tanlash
              </span>
            </Button>
            <span className="min-w-0 flex-1 truncate text-xs text-[var(--text-secondary)]">
              {profileFile ? profileFile.name : "Fayl tanlanmagan"}
            </span>
            <Button
              variant="primary"
              disabled={!profileFile || ingestState.kind === "yuklanmoqda"}
              onClick={() => void uploadProfile()}
            >
              {ingestState.kind === "yuklanmoqda" ? "Yuklanmoqda…" : "Yuklash"}
            </Button>
          </div>

          {ingestState.kind === "success" ? (
            <div className="mt-3 rounded-[10px] border border-[var(--border-hairline)] bg-[var(--bg-base)] p-3">
              <p className="text-xs text-[var(--status-online)]">
                {ingestState.data.added} bo&apos;lim qo&apos;shildi ({ingestState.data.failed}{" "}
                xato)
              </p>
              {ingestState.data.errors.length > 0 ? (
                <ul className="mt-2 space-y-1">
                  {ingestState.data.errors.map((err, i) => (
                    <li key={i} className="text-xs text-[var(--status-alert)]">
                      · {err}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}

          {ingestState.kind === "error" ? (
            <p className="mt-3 text-xs text-[var(--status-alert)]">
              Yuklab bo&apos;lmadi: {ingestState.message}
            </p>
          ) : null}
        </Panel>
      </motion.div>
    </div>
  );
}
