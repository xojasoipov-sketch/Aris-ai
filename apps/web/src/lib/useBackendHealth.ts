"use client";

/** Backend salomatligi — real GET /health poll (10s).
 * Sifat standarti: soxta "onlayn" ko'rsatkich yo'q — UI haqiqiy holatni aytadi.
 */

import { useEffect, useState } from "react";

import { api } from "@/lib/api";

export type BackendHealth = "checking" | "online" | "offline";

export function useBackendHealth(intervalMs = 10_000): BackendHealth {
  const [health, setHealth] = useState<BackendHealth>("checking");

  useEffect(() => {
    let alive = true;
    const check = async () => {
      const res = await api.health();
      if (alive) setHealth(res.ok ? "online" : "offline");
    };
    void check();
    const t = setInterval(() => void check(), intervalMs);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [intervalMs]);

  return health;
}
