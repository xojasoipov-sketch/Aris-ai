"use client";

/** Ikki marta qarsak aniqlash — mikrofon orqali (Z47).
 *
 * Ega talabi: "ikki marta qarsak cholsam «ha janob, assalomu
 * alaykum, nima xizmat» deydigan bo'lsin".
 *
 * QANDAY ISHLAYDI. Qarsak — juda qisqa va keskin tovush portlashi.
 * Uni gapdan ajratadigan narsa ikkita:
 *
 *   1. Energiya SAKRASHI — oldingi fon darajasidan keskin oshadi.
 *      Doimiy baland tovush (musiqa, shovqin) sakrash bermaydi,
 *      chunki fon o'rtachasi u bilan birga ko'tariladi.
 *   2. Yuqori chastota ulushi — qarsakda keng spektrli "chirsillash"
 *      bor; unli tovushlar esa asosan past chastotada.
 *
 * Shu ikkalasi birga bo'lmasa hisoblanmaydi — aks holda eshik
 * yopilishi yoki yo'talish ham ZET'ni uyg'otardi.
 *
 * MIKROFON RUXSATSIZ ISHLAMAYDI va bu normal: hook ruxsat holatini
 * qaytaradi, chaqiruvchi esa buni ochiq ko'rsatadi (jimgina
 * "ishlamayapti" holat qolmasin).
 */

import { useCallback, useEffect, useRef, useState } from "react";

/** Fon darajasidan necha barobar baland bo'lsa "portlash" deymiz. */
const SPIKE_RATIO = 3.2;

/** Portlash sifatida qaralishi uchun minimal mutlaq energiya.
 *
 * Jim xonada fon deyarli nol bo'ladi va NISBAT juda oson oshib
 * ketadi — bu chegara shivirlashni qarsak deb hisoblashning oldini
 * oladi. */
const MIN_ENERGY = 0.045;

/** Spektrning yuqori yarmiga tushishi kerak bo'lgan minimal ulush. */
const MIN_HIGH_RATIO = 0.34;

/** Ikkita qarsak orasidagi ruxsat etilgan oraliq (ms). */
const GAP_MIN_MS = 120;
const GAP_MAX_MS = 900;

/** Bitta qarsakdan keyingi "ko'r" oraliq — aks-sado ikkinchi
 * qarsak deb hisoblanmasligi uchun. */
const REFRACTORY_MS = 110;

export type MicPermission = "idle" | "requesting" | "granted" | "denied" | "unsupported";

export interface ClapDetector {
  permission: MicPermission;
  /** Mikrofonni yoqadi — foydalanuvchi harakati (bosish) ichida chaqirilsin. */
  enable: () => Promise<void>;
  /** Oxirgi aniqlangan darajа (0-1) — UI indikatori uchun. */
  level: number;
}

export function useClapDetector(onDoubleClap: () => void): ClapDetector {
  const [permission, setPermission] = useState<MicPermission>("idle");
  const [level, setLevel] = useState(0);

  // Callback har renderda yangi bo'lishi mumkin — audio tsiklini
  // qayta ishga tushirmaslik uchun ref orqali o'qiymiz.
  const handlerRef = useRef(onDoubleClap);
  handlerRef.current = onDoubleClap;

  const cleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => () => cleanupRef.current?.(), []);

  const enable = useCallback(async () => {
    if (cleanupRef.current) return; // allaqachon yoqilgan
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setPermission("unsupported");
      return;
    }

    setPermission("requesting");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          // Qarsak — keskin portlash. Avtomatik kuchaytirish va
          // shovqin bostirish uni "tekislab" yuboradi va aniqlash
          // sezilarli yomonlashadi.
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        },
      });
    } catch {
      setPermission("denied");
      return;
    }

    const AudioCtor =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioCtor) {
      setPermission("unsupported");
      stream.getTracks().forEach((t) => t.stop());
      return;
    }

    const ctx = new AudioCtor();
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0; // silliqlash portlashni yo'qotadi
    source.connect(analyser);

    const bins = new Uint8Array(analyser.frequencyBinCount);
    let background = 0.02;
    let lastClapAt = 0;
    let pendingClapAt = 0;
    let raf = 0;

    const tick = () => {
      analyser.getByteFrequencyData(bins);

      let total = 0;
      let high = 0;
      const mid = Math.floor(bins.length / 2);
      for (let i = 0; i < bins.length; i++) {
        const v = bins[i] / 255;
        total += v;
        if (i >= mid) high += v;
      }
      const energy = total / bins.length;
      const highRatio = total > 0 ? high / total : 0;

      setLevel(energy);

      const now = performance.now();
      const isSpike =
        energy > MIN_ENERGY &&
        energy > background * SPIKE_RATIO &&
        highRatio > MIN_HIGH_RATIO &&
        now - lastClapAt > REFRACTORY_MS;

      if (isSpike) {
        lastClapAt = now;
        const gap = now - pendingClapAt;
        if (pendingClapAt && gap > GAP_MIN_MS && gap < GAP_MAX_MS) {
          pendingClapAt = 0; // uchinchi qarsak yangi juftlik boshlasin
          handlerRef.current();
        } else {
          pendingClapAt = now;
        }
      }

      // Fon darajasi sekin moslashadi — portlashdan keyin darhol
      // ko'tarilib ketmasligi uchun juda kichik koeffitsient.
      background = background * 0.97 + energy * 0.03;
      raf = requestAnimationFrame(tick);
    };

    raf = requestAnimationFrame(tick);
    setPermission("granted");

    cleanupRef.current = () => {
      cancelAnimationFrame(raf);
      stream.getTracks().forEach((t) => t.stop());
      void ctx.close();
      cleanupRef.current = null;
    };
  }, []);

  return { permission, enable, level };
}
