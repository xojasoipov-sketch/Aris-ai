"use client";

/** NEXUS tizim jurnali — referens rasmning pastki chap burchagi (Z50).
 *
 * Rasmda vaqt tamg'ali qatorlar turadi:
 *
 *     [23:42:11] System Booted
 *     [23:42:12] Core Ready
 *     [23:42:13] Hand Tracking Active
 *
 * Bu yerdagi qatorlar HAQIQIY hodisalardan yoziladi — sahifa ochilishi,
 * kamera/mikrofon ruxsati, karta tanlash, ovozli javob. Oldindan
 * yozilgan matn EMAS: rasmdagi to'rt qator chiroyli, lekin ular hech
 * qachon o'zgarmasa, jurnal bezakka aylanadi va unga ishonib
 * bo'lmaydi.
 *
 * Qatorlar soni cheklangan (`MAX_LINES`): NEXUS uzoq ochiq turishi
 * mumkin va cheksiz massiv xotirani asta to'ldirardi.
 */

import { useCallback, useEffect, useRef, useState } from "react";

export interface LogLine {
  time: string;
  text: string;
}

const MAX_LINES = 6;

export function useSystemLog() {
  const [lines, setLines] = useState<LogLine[]>([]);
  // `push` har renderda yangi bo'lmasin — u useEffect bog'liqligida
  // ishlatiladi va yangilanib tursa cheksiz tsikl hosil bo'lardi.
  const push = useCallback((text: string) => {
    setLines((cur) => {
      const time = new Date().toLocaleTimeString("uz-UZ", { hour12: false });
      return [...cur.slice(-(MAX_LINES - 1)), { time, text }];
    });
  }, []);

  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    push("NEXUS ishga tushdi");
  }, [push]);

  return { lines, push };
}

export function SystemLog({ lines }: { lines: LogLine[] }) {
  return (
    <div className="w-[15rem] rounded-[12px] border border-[var(--border-hairline)] bg-[rgba(11,14,20,0.6)] px-3 py-2.5">
      <div className="eyebrow mb-1.5">Tizim jurnali</div>
      <ul className="space-y-0.5">
        {lines.map((line, i) => (
          <li key={`${line.time}-${i}`} className="data text-[10px] leading-relaxed">
            <span className="text-[var(--text-muted)]">[{line.time}]</span>{" "}
            <span className="text-[var(--text-secondary)]">{line.text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
