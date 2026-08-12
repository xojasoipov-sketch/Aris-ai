"use client";

/** Terminal (/terminal) — HAQIQIY buyruq va o'lchov (Z46.2).
 *
 * ILGARI NIMA BO'LGAN — bu sahifa butun ilovadagi ENG ALDAMCHI joy edi:
 *
 *   1. `SEED_LINES` qotirilgan tizim hisobotini chizardi:
 *          "Uptime: 24:13:22"
 *          "CPU: 24% · RAM: 41% · GPU: 15%"
 *      Hech biri o'lchanmagan. Serverda GPU umuman yo'q.
 *
 *   2. Har 2.5 soniyada `STREAM_LINES` dan TASODIFIY qator olinib,
 *      unga HAQIQIY `new Date()` vaqt tamg'asi qo'yib chop etilardi.
 *      Yashil pulsatsiyalanuvchi "jonli" nuqta bilan birga bu jonli
 *      tizim oqimidan farq qilmasdi — lekin bitta ham haqiqiy voqea
 *      emas edi.
 *
 *   3. `zet@core:~$` prompti va kursor bor edi, lekin KIRITISH MAYDONI
 *      yo'q — bezak.
 *
 *   4. Uch tab (`Terminal`/`Loglar`/`Tizim`) o'rnatilardi, leki `tab`
 *      render'da HECH QACHON o'qilmasdi — uchalasi bir xil ko'rinardi.
 *
 * Endi: o'lchovlar `GET /system` dan, buyruq esa `POST /run` orqali
 * HAQIQATAN bajariladi va javob ko'rsatiladi.
 */

import { CornerDownLeft, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { EmptyState } from "@/components/ui/forms";
import { Eyebrow, Panel, StatusDot } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { sound } from "@/lib/sound";
import { useResource } from "@/lib/useResource";

interface Line {
  id: number;
  kind: "command" | "result" | "error";
  text: string;
  at: string;
}

/** `74223` → `20:37:03` — uptime'ni o'qiladigan ko'rinishga. */
function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
}

export default function TerminalPage() {
  const { state } = useResource(() => api.system(), 5_000);
  const [lines, setLines] = useState<Line[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const nextId = useRef(0);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [lines]);

  const push = (kind: Line["kind"], text: string) => {
    setLines((cur) => [
      ...cur,
      { id: nextId.current++, kind, text, at: new Date().toLocaleTimeString("uz-UZ") },
    ]);
  };

  const submit = async () => {
    const message = draft.trim();
    if (!message || busy) return;
    setBusy(true);
    push("command", message);
    setDraft("");

    const res = await api.run(message);
    if (res.ok) {
      push("result", res.data.message || "(bo'sh javob)");
    } else {
      sound.play("error");
      push("error", res.error);
    }
    setBusy(false);
  };

  const metrics = state.kind === "ready" ? state.data : null;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">Terminal</h1>
        <p className="mt-0.5 text-sm text-[var(--text-secondary)]">
          Buyruq to&apos;g&apos;ridan-to&apos;g&apos;ri ZET yadrosiga yuboriladi
        </p>
      </header>

      {/* O'LCHANGAN ko'rsatkichlar. GPU yo'q — server uni o'lchamaydi. */}
      <Panel className="p-4">
        <div className="flex items-center justify-between">
          <Eyebrow>Tizim</Eyebrow>
          <div className="flex items-center gap-1.5">
            <StatusDot
              color={metrics ? "var(--status-online)" : "var(--status-offline)"}
              pulse={Boolean(metrics)}
            />
            <span className="text-[11px] text-[var(--text-secondary)]">
              {metrics ? "o'lchanmoqda" : "aloqa yo'q"}
            </span>
          </div>
        </div>

        {metrics ? (
          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
            <Metric label="CPU" value={`${metrics.cpu_percent}%`} />
            <Metric
              label="RAM"
              value={`${metrics.memory_percent}%`}
              hint={`${metrics.memory_used_mb} / ${metrics.memory_total_mb} MB`}
            />
            <Metric
              label="Disk"
              value={`${metrics.disk_percent}%`}
              hint={`${metrics.disk_free_gb} GB bo'sh`}
            />
            <Metric label="Uptime" value={formatUptime(metrics.uptime_seconds)} />
          </dl>
        ) : (
          <p className="mt-3 text-xs text-[var(--text-muted)]">
            {state.kind === "loading" ? "O'lchanmoqda…" : "Backend javob bermadi"}
          </p>
        )}
      </Panel>

      <Panel className="overflow-hidden p-0">
        <div
          ref={scrollRef}
          className="data max-h-[45vh] min-h-[220px] overflow-y-auto px-4 py-3 text-xs leading-relaxed"
        >
          {lines.length === 0 ? (
            <EmptyState
              title="Buyruq kiriting"
              hint="Masalan: “Bugungi vazifalarimni ayt” yoki “Kecha nima qildim?”"
            />
          ) : (
            lines.map((line) => (
              <div key={line.id} className="whitespace-pre-wrap">
                <span className="text-[var(--text-muted)]">{line.at} </span>
                {line.kind === "command" ? (
                  <>
                    <span className="text-[var(--accent-blue)]">zet@core:~$ </span>
                    <span className="text-[var(--text-primary)]">{line.text}</span>
                  </>
                ) : (
                  <span
                    className={
                      line.kind === "error"
                        ? "text-[var(--status-alert)]"
                        : "text-[var(--text-secondary)]"
                    }
                  >
                    {line.text}
                  </span>
                )}
              </div>
            ))
          )}
          {busy ? (
            <div className="flex items-center gap-2 text-[var(--text-muted)]">
              <Loader2 size={12} strokeWidth={1.5} className="animate-spin" aria-hidden />
              bajarilmoqda…
            </div>
          ) : null}
        </div>

        <div className="flex items-center gap-2 border-t border-[var(--border-hairline)] px-4 py-3">
          <span className="data shrink-0 text-xs text-[var(--accent-blue)]">zet@core:~$</span>
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void submit();
            }}
            disabled={busy}
            placeholder="Buyruq…"
            aria-label="Buyruq kiritish"
            className="data flex-1 bg-transparent text-xs text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)] disabled:opacity-50"
          />
          <button
            onClick={() => void submit()}
            disabled={!draft.trim() || busy}
            aria-label="Buyruqni yuborish"
            className="shrink-0 text-[var(--text-muted)] transition-colors hover:text-[var(--text-primary)] disabled:opacity-30"
          >
            <CornerDownLeft size={16} strokeWidth={1.5} aria-hidden />
          </button>
        </div>
      </Panel>
    </div>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <dt className="text-[10px] tracking-[0.08em] text-[var(--text-muted)] uppercase">{label}</dt>
      <dd className="data mt-0.5 text-sm text-[var(--text-primary)]">{value}</dd>
      {hint ? <dd className="text-[10px] text-[var(--text-muted)]">{hint}</dd> : null}
    </div>
  );
}
