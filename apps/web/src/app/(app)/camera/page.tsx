"use client";

/** Kamera (/camera) — bitta HAQIQIY kamera (Z48.3).
 *
 * ILGARI NIMA BO'LGAN. Bu sahifadagi hamma narsa o'ylab topilgan edi:
 *
 *   · OLTITA kamera nomi — "Old eshik", "Hovli", "Garaj", "Ofis",
 *     "Ombor", "Turargoh". Sozlamada esa BITTA Hikvision kanali bor.
 *   · To'rtta preset ("Uy", "Ofis", ...) — hech qayerga ulanmagan.
 *   · PTZ tugmalari — bosilganda faqat tovush chalardi.
 *   · Uchta tab ("Jonli", "Voqealar", "Xronologiya") — uchalasi ham
 *     AYNI bir ekranni ko'rsatardi.
 *
 * Ya'ni ega oltita kamerasi bordek va ularni burata oladigandek
 * ko'rinardi. `camera.snapshot` tooli esa HAQIQATAN ishlardi — faqat
 * unga interfeysdan yo'l yo'q edi.
 *
 * ENDI: bitta kamera, bitta amal — kadr olish. PTZ va presetlar OLIB
 * TASHLANDI, chunki Hikvision ISAPI PTZ ulanmagan; ular qaytarilishi
 * uchun avval backend'da haqiqiy boshqaruv bo'lishi kerak.
 */

import { Camera as CameraIcon, RefreshCw } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";

import { EmptyState } from "@/components/ui/forms";
import { Button, Eyebrow, Panel, StatusDot } from "@/components/ui/primitives";
import { api, type SnapshotDto } from "@/lib/api";
import { sound } from "@/lib/sound";
import { useResource } from "@/lib/useResource";

export default function CameraPage() {
  const info = useResource(() => api.camera.info());
  const [shot, setShot] = useState<SnapshotDto | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const configured = info.state.kind === "ready" && info.state.data.configured;

  const capture = async () => {
    setBusy(true);
    setError(null);
    const res = await api.camera.snapshot();
    if (res.ok) {
      setShot(res.data);
    } else {
      sound.play("error");
      setError(res.error);
    }
    setBusy(false);
  };

  return (
    <div className="mx-auto max-w-3xl space-y-5 px-6 py-6 lg:px-8">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">Kamera</h1>
          <p className="mt-0.5 flex items-center gap-2 text-sm text-[var(--text-secondary)]">
            <StatusDot
              color={configured ? "var(--status-online)" : "var(--status-offline)"}
            />
            {info.state.kind === "ready"
              ? info.state.data.label
              : info.state.kind === "loading"
                ? "Tekshirilmoqda…"
                : "Backend bilan aloqa yo'q"}
          </p>
        </div>

        {configured ? (
          <Button variant="primary" onClick={() => void capture()} disabled={busy}>
            <span className="flex items-center gap-2">
              <RefreshCw
                size={15}
                strokeWidth={1.5}
                className={busy ? "animate-spin" : ""}
                aria-hidden
              />
              {busy ? "Olinmoqda…" : "Kadr olish"}
            </span>
          </Button>
        ) : null}
      </header>

      {!configured && info.state.kind === "ready" ? (
        <Panel className="p-4">
          <EmptyState
            icon={CameraIcon}
            title="Kamera ulanmagan"
            hint={info.state.data.detail}
          />
        </Panel>
      ) : null}

      {configured ? (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: "easeOut" }}
        >
          <Panel className="overflow-hidden p-0">
            <div
              className="flex aspect-video items-center justify-center"
              style={{ background: "var(--bg-base)" }}
            >
              {shot ? (
                // eslint-disable-next-line @next/next/no-img-element -- data: URI, optimallashtirish kerak emas
                <img
                  src={`data:${shot.media_type};base64,${shot.image_b64}`}
                  alt="Kamera kadri"
                  className="h-full w-full object-contain"
                />
              ) : (
                <div className="flex flex-col items-center gap-2 text-[var(--text-muted)]">
                  <CameraIcon size={30} strokeWidth={1.5} aria-hidden />
                  <span className="text-xs">Kadr hali olinmagan</span>
                </div>
              )}
            </div>

            {shot ? (
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-[var(--border-hairline)] px-4 py-2.5">
                <Eyebrow>{shot.source}</Eyebrow>
                <span className="data text-[11px] text-[var(--text-muted)]">
                  {shot.width}×{shot.height}
                </span>
                <span className="data text-[11px] text-[var(--text-muted)]">
                  {new Date(shot.timestamp).toLocaleTimeString("uz-UZ")}
                </span>
              </div>
            ) : null}
          </Panel>
        </motion.div>
      ) : null}

      {error ? <p className="text-xs text-[var(--status-alert)]">Kadr olinmadi: {error}</p> : null}

      <p className="text-[11px] leading-relaxed text-[var(--text-muted)]">
        Kamerani burash (PTZ) va presetlar hali ulanmagan — backend&apos;da Hikvision ISAPI
        boshqaruvi yo&apos;q. Ishlamaydigan tugma ko&apos;rsatilmaydi.
      </p>
    </div>
  );
}
