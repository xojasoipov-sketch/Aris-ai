"use client";

/** AI Assistant holat mashinasi — docs/10-DESIGN-SYSTEM.md §3.2 Mermaid
 * diagrammasining aynan kod ko'rinishi.
 *
 *   sleep → listening → thinking → speaking → (listening | sleep)
 *   sleep ↔ minimized · thinking → notification → listening
 *
 * Har bir o'tishda mos tovush chalinadi (lib/sound.ts) — vizual (zarracha),
 * audio va mantiq bitta manbadan boshqariladi.
 */

import { useCallback, useEffect, useReducer, useRef } from "react";

import { sound } from "@/lib/sound";

export type AssistantState =
  | "sleep"
  | "listening"
  | "thinking"
  | "speaking"
  | "minimized"
  | "notification";

export type AssistantEvent =
  | "WAKE" // foydalanuvchi chaqirdi (ovoz/matn/tap)
  | "SUBMIT" // so'rov yuborildi
  | "RESPOND" // javob tayyor / kela boshladi
  | "DONE" // javob tugadi (suhbat davom etadi)
  | "CANCEL" // bekor / timeout
  | "MINIMIZE" // boshqa ilovaga o'tildi
  | "RESTORE" // orb bosildi
  | "NOTIFY" // fon vazifasi tugadi
  | "OPEN_NOTIFICATION"; // bildirishnoma ochildi

/** Ruxsat etilgan o'tishlar — diagrammadan tashqari o'tish YO'Q. */
const TRANSITIONS: Record<AssistantState, Partial<Record<AssistantEvent, AssistantState>>> = {
  sleep: { WAKE: "listening", MINIMIZE: "minimized" },
  listening: { SUBMIT: "thinking", CANCEL: "sleep", MINIMIZE: "minimized" },
  thinking: { RESPOND: "speaking", CANCEL: "sleep", NOTIFY: "notification" },
  speaking: { DONE: "listening", CANCEL: "sleep" },
  minimized: { RESTORE: "listening", NOTIFY: "notification" },
  notification: { OPEN_NOTIFICATION: "listening", CANCEL: "sleep" },
};

/** O'tish tovushlari — "qaysi holatGA kirdik" bo'yicha. */
function playFor(prev: AssistantState, next: AssistantState): void {
  if (prev === "thinking") sound.stopThinking();
  switch (next) {
    case "listening":
      sound.play(prev === "sleep" || prev === "minimized" ? "wake" : "listenStart");
      break;
    case "thinking":
      sound.startThinking();
      break;
    case "speaking":
      sound.play("speak");
      break;
    case "sleep":
      sound.play("sleep");
      break;
    case "notification":
      sound.play("notification");
      break;
    case "minimized":
      break;
  }
}

function reducer(state: AssistantState, event: AssistantEvent): AssistantState {
  return TRANSITIONS[state][event] ?? state;
}

export function useAssistant(initial: AssistantState = "sleep") {
  const [state, dispatch] = useReducer(reducer, initial);
  const prevRef = useRef(state);

  useEffect(() => {
    if (prevRef.current !== state) {
      playFor(prevRef.current, state);
      prevRef.current = state;
    }
  }, [state]);

  const send = useCallback((event: AssistantEvent) => dispatch(event), []);

  return { state, send } as const;
}

/** Holat → o'zbekcha yorliq (UI matni uchun). */
export const STATE_LABEL: Record<AssistantState, string> = {
  sleep: "Hammasi nazoratda. Kerak bo'lsam — shu yerdaman.",
  listening: "Eshityapman...",
  thinking: "O'ylayapman...",
  speaking: "Javob beryapman...",
  minimized: "Chetda kutyapman",
  notification: "Yangi xabar bor",
};
