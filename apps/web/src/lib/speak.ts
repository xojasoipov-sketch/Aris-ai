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
 *
 * QACHON HAL BO'LADI (F7a — muhim):
 * `speak()` qaytargan promise ovoz HAQIQATAN TUGAGANDA hal bo'ladi,
 * ijro boshlanganda emas. Sabab: chaqiruvchi (nexus sahnasi) ZET
 * gapirib bo'lgach mikrofonni ochadi. Agar promise boshlanishda hal
 * bo'lsa, chaqiruvchi taxminiy timeout'ga tayanishga majbur bo'ladi
 * va uzunroq javoblarda mikrofon ZET hali gapirayotganda ochilib,
 * O'Z OVOZINI eshitib qoladi. Shuning uchun bu yerda haqiqiy
 * hodisalar kutiladi: audio'da `ended`/`error`/`pause`, brauzer
 * ovozida `onend`/`onerror`.
 *
 * OSILIB QOLMASLIK KAFOLATI: har bir yo'lda bir nechta tugash
 * hodisasiga bir martalik listener qo'yiladi va BIRINCHI kelgani
 * promise'ni hal qiladi. Shu sabab xato yuz bersa ham,
 * `stopSpeaking()` chaqirilsa ham kutayotgan promise albatta
 * yopiladi.
 */

let current: HTMLAudioElement | null = null;

/** Oldingi javobni to'xtatadi — ikkita ovoz ustma-ust chiqmasin.
 *
 * Tashqi interfeys o'zgarmagan. To'xtatish `pause()` va
 * `speechSynthesis.cancel()` orqali mos hodisalarni uyg'otadi, shu
 * sabab kutayotgan `speak()` promise'i ham shu yerda yopiladi. */
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

/** Server audio'si tugaguncha kutadi.
 *
 * Uchta hodisa ham tugash signali:
 *   - `ended` — ovoz oxirigacha o'qildi (normal yo'l)
 *   - `error` — manba buzilgan yoki `src` bo'shatilgan
 *   - `pause` — `stopSpeaking()` chaqirildi
 * Birinchi kelgani promise'ni hal qiladi; qolgan listener'lar
 * o'chiriladi. Blob URL ham AYNAN shu yerda bo'shatiladi — qaysi
 * yo'l bilan tugashidan qat'i nazar xotira qolib ketmasin. */
function waitForAudioEnd(audio: HTMLAudioElement, objectUrl: string): Promise<void> {
  return new Promise((resolve) => {
    let settled = false;

    const finish = () => {
      if (settled) return;
      settled = true;
      audio.removeEventListener("ended", finish);
      audio.removeEventListener("error", finish);
      audio.removeEventListener("pause", finish);
      // Blob URL'ni bo'shatamiz — aks holda har javob xotirada qoladi.
      URL.revokeObjectURL(objectUrl);
      // Faqat O'ZIMIZNI tozalaymiz — yangi ovoz boshlangan bo'lsa tegmaymiz.
      if (current === audio) current = null;
      resolve();
    };

    audio.addEventListener("ended", finish, { once: true });
    audio.addEventListener("error", finish, { once: true });
    audio.addEventListener("pause", finish, { once: true });

    // Listener qo'yilgunicha ijro tugab/to'xtab ulgurgan bo'lishi
    // mumkin — bunda hech qanday hodisa kelmaydi, shuning uchun
    // holatni darhol tekshiramiz.
    if (audio.ended || audio.paused) finish();
  });
}

/** Brauzer ovozi tugaguncha kutadi.
 *
 * `onend` — normal tugash yoki `cancel()`; `onerror` — ovoz topilmadi,
 * sintez uzildi va h.k. Ikkalasi ham tugash signali. */
function waitForUtteranceEnd(utterance: SpeechSynthesisUtterance): Promise<void> {
  return new Promise((resolve) => {
    let settled = false;

    const finish = () => {
      if (settled) return;
      settled = true;
      utterance.onend = null;
      utterance.onerror = null;
      resolve();
    };

    utterance.onend = finish;
    utterance.onerror = finish;
  });
}

/**
 * Matnni ovozda o'qiydi va OVOZ TUGAGANDA hal bo'ladi.
 *
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
      // `play()` ijro BOSHLANGANDA qaytadi — shundan keyin tugashni
      // kutamiz. (Kutishni play'dan oldin ulab bo'lmaydi: yangi
      // Audio elementi hali `paused` holatida bo'ladi.)
      try {
        await audio.play();
      } catch (err) {
        // Ijro umuman boshlanmadi (masalan autoplay bloklandi) —
        // blob'ni bo'shatamiz va quyidagi catch orqali brauzer
        // ovoziga tushamiz.
        URL.revokeObjectURL(url);
        if (current === audio) current = null;
        throw err;
      }
      await waitForAudioEnd(audio, url);
      return "server";
    }
  } catch {
    // Tarmoq xatosi — brauzer ovoziga tushamiz.
  }

  if (typeof window !== "undefined" && "speechSynthesis" in window) {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "uz-UZ";
    utterance.rate = 0.95;
    // Hodisalar navbatga qo'yishdan OLDIN ulanadi.
    const finished = waitForUtteranceEnd(utterance);
    window.speechSynthesis.speak(utterance);
    await finished;
    return "browser";
  }

  return "none";
}

/** Ega ikki marta qarsak chalganda ZET aytadigan javob. */
export const GREETING = "Ha janob, assalomu alaykum. Nima xizmat?";
