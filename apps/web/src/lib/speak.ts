"use client";

/** Ovozli javob — server TTS, brauzer zaxirasi bilan (Z47).
 *
 * IKKI BOSQICH, chunki bittasi yetarli emas:
 *
 *   1. Server (`POST /voice/speak`) — Azure'ning HAQIQIY o'zbek
 *      neyron ovozi (`uz-UZ-SardorNeural`). Sifati eng yaxshisi.
 *   2. Brauzer `speechSynthesis` — server TTS sozlanmagan bo'lsa
 *      (503) ishlatiladi. O'zbek ovozi odatda yo'q, shuning uchun
 *      taxminan o'qiydi — lekin JIM QOLGANDAN ma'qul.
 *
 * Ovoz ijro etish uchun brauzer FOYDALANUVCHI HARAKATINI talab
 * qiladi (autoplay siyosati). Shu sabab birinchi ijro doim
 * bosishdan keyin bo'lishi kerak — sahifa o'zi ochilganda emas.
 */

let current: HTMLAudioElement | null = null;

/** Oldingi javobni to'xtatadi — ikkita ovoz ustma-ust chiqmasin. */
export function stopSpeaking(): void {
  if (current) {
    current.pause();
    current.src = "";
    current = null;
  }
  if (typeof window !== "undefined" && "speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }
}

export type SpeakSource = "server" | "browser" | "none";

/**
 * @returns qaysi manba ishlatilgani — UI buni ochiq ko'rsatishi uchun
 *   ("brauzer ovozi" ≠ "haqiqiy o'zbek ovozi").
 */
export async function speak(text: string): Promise<SpeakSource> {
  stopSpeaking();

  try {
    const res = await fetch("/api/zet/voice/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, language: "uz" }),
    });

    if (res.ok) {
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      current = audio;
      // Blob URL'ni bo'shatamiz — aks holda har javob xotirada qoladi.
      audio.addEventListener("ended", () => URL.revokeObjectURL(url), { once: true });
      await audio.play();
      return "server";
    }
  } catch {
    // Tarmoq xatosi — brauzer ovoziga tushamiz.
  }

  if (typeof window !== "undefined" && "speechSynthesis" in window) {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "uz-UZ";
    utterance.rate = 0.95;
    window.speechSynthesis.speak(utterance);
    return "browser";
  }

  return "none";
}

/** Ega ikki marta qarsak chalganda ZET aytadigan javob. */
export const GREETING = "Ha janob, assalomu alaykum. Nima xizmat?";
