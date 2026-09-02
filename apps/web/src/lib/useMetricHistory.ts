"use client";

/** Ko'rsatkich tarixi — sparkline uchun mahalliy bufer (Z50.1).
 *
 * NEGA MAHALLIY. Backend `/system` faqat HOZIRGI qiymatni beradi —
 * tarix saqlamaydi (buning uchun vaqt qatoriga yoziladigan alohida
 * jadval kerak bo'lardi, hozircha ortiqcha). Sparkline chizish uchun
 * esa bir nechta nuqta kerak.
 *
 * Shu sabab tarix BRAUZERDA yig'iladi: sahifa ochiq turgan davrda har
 * yangi o'lchov oxiriga qo'shiladi. Sahifa yangilansa boshidan
 * boshlanadi — bu OCHIQ tan olinadi, soxta "so'nggi bir soat" tarixi
 * chizilmaydi.
 */

import { useEffect, useRef, useState } from "react";

const MAX_POINTS = 20;

export function useMetricHistory(value: number | null): number[] {
  const [history, setHistory] = useState<number[]>([]);
  const lastRef = useRef<number | null>(null);

  useEffect(() => {
    if (value === null || value === lastRef.current) return;
    lastRef.current = value;
    setHistory((cur) => [...cur.slice(-(MAX_POINTS - 1)), value]);
  }, [value]);

  return history;
}
