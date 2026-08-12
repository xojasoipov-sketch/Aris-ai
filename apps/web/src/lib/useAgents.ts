"use client";

/** Haqiqiy agentlar ro'yxati — backend `GET /agents` dan (Z44).
 *
 * Ilgari dashboard'da beshta QOTIRILGAN agent turardi:
 *
 *     const AGENTS = [
 *       { name: "CEO Agent", division: "Strategiya", status: "online" },
 *       { name: "SMM Agent", division: "Marketing", status: "working" },
 *       ...
 *     ]
 *
 * Backendda esa 12 ta haqiqiy agent bor va ularning holati boshqacha.
 * Ega buni ko'rib "ko'p joyi soxta" dedi — haqli.
 *
 * `status` backend `AgentStatus` dan keladi (draft/testing/active/
 * paused/disabled/archived) — brauzerda o'ylab topilmaydi.
 */

import { useEffect, useState } from "react";

import { type AgentDto, api } from "@/lib/api";

export type AgentsState =
  | { kind: "loading" }
  | { kind: "ready"; agents: AgentDto[] }
  | { kind: "error"; message: string };

export function useAgents(intervalMs = 15_000): AgentsState {
  const [state, setState] = useState<AgentsState>({ kind: "loading" });

  useEffect(() => {
    let alive = true;
    const load = async () => {
      const res = await api.agents();
      if (!alive) return;
      setState(
        res.ok ? { kind: "ready", agents: res.data } : { kind: "error", message: res.error },
      );
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
