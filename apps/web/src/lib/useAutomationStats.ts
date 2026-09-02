"use client";

/** Avtomatlashtirish statistikasi — backend `GET /automation/stats` (Z44).
 *
 * Ilgari dashboard'ning "Tizim" paneli CPU 26% / RAM 40% / Disk 32% deb
 * ko'rsatardi. Bu uch raqam ham QOTIRILGAN edi va ZET ularni umuman
 * o'lchamaydi — u konteynerda ishlaydi, host metrikalari uning ishi
 * emas. O'rniga backend HAQIQATAN beradigan hisoblagichlar ko'rsatiladi:
 * faol jadval, trigger va kuzatuv qoidalari.
 */

import { useEffect, useState } from "react";

import { type AutomationStatsDto, api } from "@/lib/api";

export type AutomationStatsState =
  | { kind: "loading" }
  | { kind: "ready"; data: AutomationStatsDto }
  | { kind: "error"; message: string };

export function useAutomationStats(intervalMs = 15_000): AutomationStatsState {
  const [state, setState] = useState<AutomationStatsState>({ kind: "loading" });

  useEffect(() => {
    let alive = true;
    const load = async () => {
      const res = await api.automationStats();
      if (!alive) return;
      setState(res.ok ? { kind: "ready", data: res.data } : { kind: "error", message: res.error });
    };
    void load();
    const t = setInterval(() => void load(), intervalMs);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [intervalMs]);

  return state;
}
