"use client";

/** Backend resursini yuklovchi umumiy hook (Z46.2).
 *
 * NEGA UMUMIY HOOK.
 *
 * `useAgents`, `useAutomationStats`, `useBackendHealth` — uchalasi ham
 * bir xil naqshni takrorlardi (loading → ready/error, interval bilan
 * yangilash, unmount'da bekor qilish). Yangi sahifalar (loyihalar,
 * vazifalar, kalendar, tizim, integratsiyalar) bilan bu yana beshta
 * nusxa bo'lardi.
 *
 * Muhim: `reload()` qaytariladi — o'zgartirishdan (POST/PATCH/DELETE)
 * keyin ro'yxatni qayta o'qish uchun. Ilgari sahifalar mahalliy
 * holatni o'zgartirib qo'ya qolardi va bu "saqlandi" degan yolg'on
 * taassurot berardi (backend'ga hech narsa bormasa ham).
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { Result } from "@/lib/api";

export type ResourceState<T> =
  | { kind: "loading" }
  | { kind: "ready"; data: T }
  | { kind: "error"; message: string };

export interface Resource<T> {
  state: ResourceState<T>;
  reload: () => Promise<void>;
}

/**
 * @param fetcher Backend chaqiruvi — `Result` qaytaradi, istisno otmaydi.
 * @param intervalMs 0 bo'lsa avtomatik yangilash O'CHIQ (masalan
 *   foydalanuvchi tahrirlayotgan ro'yxat — ostidan almashib ketmasin).
 */
export function useResource<T>(
  fetcher: () => Promise<Result<T>>,
  intervalMs = 0,
): Resource<T> {
  const [state, setState] = useState<ResourceState<T>>({ kind: "loading" });

  // `fetcher` har renderda yangi funksiya bo'ladi (inline lambda).
  // Uni to'g'ridan-to'g'ri dependency qilsak effekt cheksiz qayta
  // ishga tushardi. Ref orqali oxirgi versiyani saqlaymiz.
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const aliveRef = useRef(true);

  const load = useCallback(async () => {
    const res = await fetcherRef.current();
    if (!aliveRef.current) return;
    setState(res.ok ? { kind: "ready", data: res.data } : { kind: "error", message: res.error });
  }, []);

  useEffect(() => {
    aliveRef.current = true;
    void load();
    if (intervalMs <= 0) {
      return () => {
        aliveRef.current = false;
      };
    }
    const timer = setInterval(() => void load(), intervalMs);
    return () => {
      aliveRef.current = false;
      clearInterval(timer);
    };
  }, [load, intervalMs]);

  return { state, reload: load };
}
