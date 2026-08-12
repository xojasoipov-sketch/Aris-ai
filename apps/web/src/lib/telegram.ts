"use client";

/** Telegram WebApp yordamchisi — Mini App (/tg) uchun.
 *
 * Rasmiy telegram-web-app.js global `window.Telegram.WebApp` beradi.
 * Telegram tashqarisida ochilsa — hammasi no-op, sahifa oddiy ishlayveradi.
 *
 * Xavfsizlik: initData backend'da (R-04 owner tekshiruvi) validatsiya
 * qilinadi — frontend uni faqat uzatadi, ishonmaydi.
 */

interface TelegramWebApp {
  initData: string;
  ready: () => void;
  expand: () => void;
  themeParams?: { bg_color?: string; text_color?: string };
  colorScheme?: "light" | "dark";
  HapticFeedback?: { impactOccurred: (style: "light" | "medium") => void };
}

export function getTelegramWebApp(): TelegramWebApp | null {
  if (typeof window === "undefined") return null;
  const tg = (window as unknown as { Telegram?: { WebApp?: TelegramWebApp } }).Telegram?.WebApp;
  return tg ?? null;
}

/** Mini App'ni ishga tayyorlash: ready + expand + tema moslash. */
export function initTelegramApp(): TelegramWebApp | null {
  const tg = getTelegramWebApp();
  if (!tg) return null;
  tg.ready();
  tg.expand();
  // Telegram temasi qora bo'lmasa ham biz o'z fonimizni saqlaymiz —
  // faqat juda och temalarda matn kontrastini himoya qilamiz (master
  // tizim: fon doim #050608 atrofida qoladi).
  return tg;
}

/** Haptic — tugma bosilganda telefon tebranishi (bor bo'lsa). */
export function haptic(style: "light" | "medium" = "light"): void {
  getTelegramWebApp()?.HapticFeedback?.impactOccurred(style);
}
