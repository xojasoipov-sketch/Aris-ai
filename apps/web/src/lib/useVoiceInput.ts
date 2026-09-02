"use client";

/** Ovozni matnga aylantirish — brauzer Web Speech API orqali (Z47).
 *
 * QANDAY ISHLAYDI. `SpeechRecognition` (Chrome/Edge'da `webkitSpeechRecognition`
 * nomi bilan) mikrofon oqimini brauzer/OS darajasida tanib, matn qaytaradi —
 * bizga hech qanday audio ishlov berish yoki server kerak emas.
 *
 * `interimResults: true` bilan har bir kadrda ORALIQ (hali tugallanmagan)
 * natija ham keladi — buni `transcript`ga yozamiz, shunda foydalanuvchi
 * gapirayotganda matn jonli (real-time) ko'rinadi. Natija YAKUNIY
 * (`isFinal`) bo'lganda esa `onFinalResult` chaqiriladi va tinglash
 * avtomatik to'xtaydi (`continuous: false` — bitta gap, bitta natija).
 *
 * BU BRAUZER API'SI, BACKEND EMAS: barcha nutqni-tanib-olish ishi
 * qurilma/brauzer ichida bo'ladi, tarmoqqa audio yubormaymiz.
 *
 * QO'LLAB-QUVVATLANMASA yoki RUXSAT RAD ETILSA — hook buni ochiq holat
 * sifatida qaytaradi ("unsupported" / "denied" / "error" + sabab matni).
 * Hech qachon "ishladi" deb soxta muvaffaqiyat ko'rsatilmaydi.
 *
 * TIPLAR HAQIDA: standart `lib.dom.d.ts`da `SpeechRecognition` turlari
 * yo'q (hali W3C standarti emas) — shu sababli quyida faqat bizga kerak
 * bo'lgan minimal interfeys qo'lda e'lon qilingan.
 */

import { useCallback, useEffect, useRef, useState } from "react";

/** Bitta tanilgan natija — final yoki oraliq bo'lishi mumkin. */
interface MinimalSpeechRecognitionResult {
  readonly isFinal: boolean;
  readonly length: number;
  readonly [index: number]: { readonly transcript: string };
}

interface MinimalSpeechRecognitionResultList {
  readonly length: number;
  readonly [index: number]: MinimalSpeechRecognitionResult;
}

interface MinimalSpeechRecognitionEvent extends Event {
  readonly resultIndex: number;
  readonly results: MinimalSpeechRecognitionResultList;
}

interface MinimalSpeechRecognitionErrorEvent extends Event {
  readonly error: string;
}

interface MinimalSpeechRecognition extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onstart: (() => void) | null;
  onresult: ((event: MinimalSpeechRecognitionEvent) => void) | null;
  onerror: ((event: MinimalSpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
}

interface MinimalSpeechRecognitionConstructor {
  new (): MinimalSpeechRecognition;
}

export type VoicePermission =
  | "idle"
  | "requesting"
  | "listening"
  | "denied"
  | "unsupported"
  | "error";

export interface VoiceInput {
  permission: VoicePermission;
  /** Oxirgi tanilgan (interim + final) matn. */
  transcript: string;
  /** Xato sababi — `permission === "error"` bo'lganda. */
  error: string;
  /** Tinglashni boshlaydi — foydalanuvchi harakati (bosish) ichida chaqirilsin. */
  start: () => void;
  /** Tinglashni to'xtatadi. */
  stop: () => void;
}

export function useVoiceInput(onFinalResult: (text: string) => void): VoiceInput {
  const [permission, setPermission] = useState<VoicePermission>("idle");
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState("");

  // Callback har renderda yangi bo'lishi mumkin — recognition tsiklini
  // qayta yaratmaslik uchun ref orqali o'qiymiz.
  const handlerRef = useRef(onFinalResult);
  handlerRef.current = onFinalResult;

  const recognitionRef = useRef<MinimalSpeechRecognition | null>(null);

  // `onend` ichida "hali listening edikmi" degan savolga javob berish uchun
  // state'ning eng so'nggi qiymati kerak — React state closure'da eskirib
  // qolishi mumkin, shuning uchun ref bilan sinxron kuzatamiz.
  const permissionRef = useRef<VoicePermission>("idle");
  const applyPermission = useCallback((next: VoicePermission) => {
    permissionRef.current = next;
    setPermission(next);
  }, []);

  useEffect(() => () => recognitionRef.current?.abort(), []);

  const stop = useCallback(() => {
    recognitionRef.current?.stop();
  }, []);

  const start = useCallback(() => {
    if (recognitionRef.current) return; // allaqachon tinglanmoqda

    const w = window as unknown as {
      SpeechRecognition?: MinimalSpeechRecognitionConstructor;
      webkitSpeechRecognition?: MinimalSpeechRecognitionConstructor;
    };
    const SpeechRecognitionCtor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
    if (typeof window === "undefined" || !SpeechRecognitionCtor) {
      applyPermission("unsupported");
      return;
    }

    setError("");
    setTranscript("");
    applyPermission("requesting");

    const recognition = new SpeechRecognitionCtor();
    recognition.lang = "uz-UZ";
    recognition.continuous = false;
    recognition.interimResults = true;

    recognition.onstart = () => {
      applyPermission("listening");
    };

    recognition.onresult = (event) => {
      let interim = "";
      let final = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        const text = result[0].transcript;
        if (result.isFinal) {
          final += text;
        } else {
          interim += text;
        }
      }

      if (final) {
        setTranscript(final);
        handlerRef.current(final);
        // Natija yakunlandi — tugma abadiy "tinglanmoqda" holatida
        // qolib ketmasligi uchun darhol idle'ga qaytaramiz va
        // recognition'ni to'xtatamiz (u baribir tez orada tugaydi).
        applyPermission("idle");
        recognition.stop();
      } else {
        setTranscript(interim);
      }
    };

    recognition.onerror = (event) => {
      if (event.error === "not-allowed") {
        applyPermission("denied");
      } else {
        applyPermission("error");
        setError(`Nutqni tanib olishda xato: ${event.error}`);
      }
    };

    recognition.onend = () => {
      recognitionRef.current = null;
      // Faqat foydalanuvchi to'xtatmagan, brauzer o'zi tugatgan holatda
      // (hali "listening" bo'lsa) idle'ga qaytaramiz — aks holda yuqorida
      // "denied"/"error"/"idle" allaqachon o'rnatilgan bo'ladi.
      if (permissionRef.current === "listening") {
        applyPermission("idle");
      }
    };

    recognitionRef.current = recognition;

    try {
      recognition.start();
    } catch (e) {
      recognitionRef.current = null;
      applyPermission("error");
      setError(e instanceof Error ? e.message : "Nutqni tanib olish boshlanmadi");
    }
  }, [applyPermission]);

  return { permission, transcript, error, start, stop };
}
