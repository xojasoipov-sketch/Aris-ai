"use client";

/** Sozlamalar (/settings) — FAZA 4 speci: bo'limlar, accent-color picker
 * (haqiqiy ishlaydi — --accent-blue ni almashtiradi), toggle'lar.
 *
 * Xavfsizlik: integratsiyalarda faqat sozlangan/sozlanmagan HOLAT (bool)
 * ko'rsatiladi — hech qanday sir (SecretStr) frontend'ga chiqmaydi.
 */

import { motion } from "motion/react";
import { useState } from "react";

import { SettingsRow as Row, Toggle } from "@/components/ui/forms";
import { Eyebrow, Panel, StatusDot } from "@/components/ui/primitives";
import { sound } from "@/lib/sound";

/* Accent variantlari — master tizim default: #4C8DFF */
const ACCENTS = ["#4C8DFF", "#22C55E", "#F59E0B", "#EC4899", "#A78BFA", "#EF4444"] as const;

const INTEGRATIONS = [
  { name: "Telegram bot", configured: true },
  { name: "ElevenLabs (ovoz)", configured: true },
  { name: "Google Gemini (T1)", configured: true },
  { name: "Mistral (T1)", configured: true },
  { name: "YouTube Data API", configured: false },
  { name: "Instagram Graph API", configured: false },
  { name: "GitHub", configured: false },
] as const;

export default function SettingsPage() {
  const [accent, setAccent] = useState<string>(ACCENTS[0]);
  const [soundOn, setSoundOn] = useState(true);
  const [nightMode, setNightMode] = useState(true);
  const [notifs, setNotifs] = useState(true);

  const applyAccent = (c: string) => {
    setAccent(c);
    document.documentElement.style.setProperty("--accent-blue", c);
    sound.play("tick");
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
            <Row label="Tungi rejim">
              <Toggle on={nightMode} onChange={setNightMode} />
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
            <Row label="Bildirishnomalar">
              <Toggle on={notifs} onChange={setNotifs} />
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
            {INTEGRATIONS.map((i) => (
              <Row key={i.name} label={i.name}>
                <div className="flex items-center gap-2">
                  <StatusDot
                    color={i.configured ? "var(--status-online)" : "var(--status-offline)"}
                  />
                  <span
                    className="text-xs"
                    style={{
                      color: i.configured ? "var(--status-online)" : "var(--text-muted)",
                    }}
                  >
                    {i.configured ? "Sozlangan" : "Sozlanmagan"}
                  </span>
                </div>
              </Row>
            ))}
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
      </motion.div>
    </div>
  );
}
