"use client";

/** Agentlar (/agents) — endi ko'rish EMAS, boshqarish (Z48.4).
 *
 * Z44'da ro'yxat haqiqiy bo'ldi (`GET /agents`) — ilgari bu yerda
 * oltita QOTIRILGAN agent turardi, nomlari va holatlari qo'lda
 * yozilgan edi ("Finance Agent · offline"), holbuki backendda 12 ta
 * agent bor.
 *
 * Lekin sahifada BITTA HAM amal yo'q edi: ega o'n ikkita agentini
 * ko'rib turardi va ularning hech biriga ish bera olmasdi. Backend'da
 * esa ikkala endpoint ham tayyor turardi:
 *
 *     POST  /agents/{name}/run      — agentga vazifa berish
 *     PATCH /agents/{name}/status   — to'xtatish / qayta yoqish (V-11)
 *
 * Endi ular ulangan. Javob HAQIQIY LLM natijasi — qisqartirilmaydi va
 * bezatilmaydi; agent yiqilsa xato matni o'zi ko'rsatiladi.
 */

import { Bot, Loader2, Pause, Play, Send } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";

import { NeuroOrb, type OrbState } from "@/components/core/NeuroOrb";
import { EmptyState } from "@/components/ui/forms";
import { Button, Eyebrow, Panel, StatusDot } from "@/components/ui/primitives";
import { api, type AgentDto, type AgentRunResultDto } from "@/lib/api";
import { sound } from "@/lib/sound";
import { useResource } from "@/lib/useResource";

type UiStatus = "online" | "offline" | "paused";

const STATUS_META: Record<UiStatus, { color: string; label: string; orb: OrbState }> = {
  online: { color: "var(--status-online)", label: "Faol", orb: "idle" },
  paused: { color: "var(--status-offline)", label: "To'xtatilgan", orb: "offline" },
  offline: { color: "var(--status-offline)", label: "Faol emas", orb: "offline" },
};

/** Backend `AgentStatus` → UI holati (faqat backend asoslay oladigani). */
function toUiStatus(status: string): UiStatus {
  if (status === "active") return "online";
  if (status === "paused") return "paused";
  return "offline";
}

/** Kartaning ikkinchi qatori — agentning HAQIQIY ish tarixi. */
function runSummary(agent: AgentDto): string {
  if (agent.total_runs === 0) return "hali ishga tushmagan";
  const pct = Math.round(agent.success_rate * 100);
  return `${agent.total_runs} run · ${pct}% muvaffaqiyat`;
}

export default function AgentsPage() {
  const { state, reload } = useResource(() => api.agents(), 15_000);
  const [open, setOpen] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<Record<string, AgentRunResultDto | string>>({});

  const agents = state.kind === "ready" ? state.data : [];

  const send = async (name: string) => {
    const task = draft.trim();
    if (!task) return;
    setBusy(name);

    const res = await api.agent.run(name, task);
    if (res.ok) {
      if (!res.data.success) sound.play("error");
      setResult((prev) => ({ ...prev, [name]: res.data }));
    } else {
      sound.play("error");
      setResult((prev) => ({ ...prev, [name]: res.error }));
    }

    setBusy(null);
    setDraft("");
    // Run soni va muvaffaqiyat ulushi backend'da yangilandi.
    await reload();
  };

  const toggle = async (agent: AgentDto) => {
    const action = toUiStatus(agent.status) === "online" ? "pause" : "activate";
    setBusy(agent.name);
    const res = await api.agent.setStatus(agent.name, action);
    if (!res.ok) {
      sound.play("error");
      setResult((prev) => ({ ...prev, [agent.name]: res.error }));
    }
    setBusy(null);
    await reload();
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-6 py-6 lg:px-8">
      <div className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">Agentlar</h1>
        <Eyebrow>
          {state.kind === "ready" ? `${agents.length} ta · registry` : "yuklanmoqda"}
        </Eyebrow>
      </div>

      {state.kind !== "ready" || agents.length === 0 ? (
        <Panel className="p-6">
          <EmptyState
            icon={Bot}
            title={state.kind === "loading" ? "Yuklanmoqda…" : "Agentlar topilmadi"}
            hint={state.kind === "error" ? state.message : "Backend registry bo'sh yoki ulanmagan"}
          />
        </Panel>
      ) : (
        <div className="grid items-start gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {agents.map((a, i) => {
            const ui = toUiStatus(a.status);
            const meta = STATUS_META[ui];
            const outcome = result[a.name];
            const working = busy === a.name;

            return (
              <motion.div
                key={a.name}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.04 * i, duration: 0.35, ease: "easeOut" }}
              >
                <Panel className="flex h-full flex-col p-5">
                  <div className="flex items-start justify-between">
                    <NeuroOrb
                      state={working ? "thinking" : meta.orb}
                      mini
                      seedOffset={i + 1}
                      className="h-14 w-14"
                    />
                    <div className="flex items-center gap-2">
                      <StatusDot color={meta.color} pulse={working} />
                      <span className="text-xs" style={{ color: meta.color }}>
                        {working ? "Ishlamoqda…" : meta.label}
                      </span>
                    </div>
                  </div>

                  <div className="mt-3 flex-1">
                    <div className="text-sm font-medium text-[var(--text-primary)]">{a.name}</div>
                    <div className="mt-0.5 text-xs text-[var(--text-muted)]">{a.division}</div>
                    <p className="mt-2 text-xs leading-relaxed text-[var(--text-secondary)]">
                      {a.description}
                    </p>
                  </div>

                  <div className="mt-4 flex items-center justify-between border-t border-[var(--border-hairline)] pt-3">
                    <span className="data text-[11px] text-[var(--text-muted)]">
                      {runSummary(a)}
                    </span>
                    <span className="data text-[11px] text-[var(--text-muted)]">
                      {a.tool_allowlist.length} tool
                    </span>
                  </div>

                  <div className="mt-3 flex gap-2">
                    {ui === "online" ? (
                      <Button
                        variant="ghost"
                        className="flex-1 text-xs"
                        onClick={() => {
                          setOpen(open === a.name ? null : a.name);
                          setDraft("");
                        }}
                        aria-expanded={open === a.name}
                        disabled={working}
                      >
                        Vazifa berish
                      </Button>
                    ) : (
                      <span className="flex-1 self-center text-[11px] text-[var(--text-muted)]">
                        Faol emas — vazifa bermaydi
                      </span>
                    )}

                    <Button
                      variant="ghost"
                      onClick={() => void toggle(a)}
                      disabled={working || (ui === "offline" && a.status !== "paused")}
                      aria-label={ui === "online" ? "To'xtatish" : "Yoqish"}
                    >
                      {ui === "online" ? (
                        <Pause size={14} strokeWidth={1.5} aria-hidden />
                      ) : (
                        <Play size={14} strokeWidth={1.5} aria-hidden />
                      )}
                    </Button>
                  </div>

                  {open === a.name ? (
                    <div className="mt-3 flex gap-2">
                      <input
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && !e.shiftKey) {
                            e.preventDefault();
                            void send(a.name);
                          }
                        }}
                        disabled={working}
                        placeholder="Nima qilsin?"
                        aria-label={`${a.name} uchun vazifa`}
                        className="min-w-0 flex-1 rounded-[10px] border border-[var(--border-hairline)] bg-[var(--bg-base)] px-3 py-2 text-xs text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)] focus-visible:border-[var(--border-active)] disabled:opacity-50"
                      />
                      <Button
                        variant="primary"
                        onClick={() => void send(a.name)}
                        disabled={!draft.trim() || working}
                        aria-label="Yuborish"
                      >
                        {working ? (
                          <Loader2 size={14} strokeWidth={1.5} className="animate-spin" aria-hidden />
                        ) : (
                          <Send size={14} strokeWidth={1.5} aria-hidden />
                        )}
                      </Button>
                    </div>
                  ) : null}

                  {outcome ? (
                    <div className="mt-3 rounded-[10px] border border-[var(--border-hairline)] bg-[var(--bg-base)] px-3 py-2.5">
                      {typeof outcome === "string" ? (
                        <p className="text-[11px] text-[var(--status-alert)]">{outcome}</p>
                      ) : (
                        <>
                          <Eyebrow>
                            {outcome.success ? "Javob" : "Bajarilmadi"} ·{" "}
                            {outcome.tool_calls_count} tool
                          </Eyebrow>
                          <pre className="mt-1.5 max-h-48 overflow-auto text-[11px] leading-relaxed whitespace-pre-wrap text-[var(--text-secondary)]">
                            {outcome.output || outcome.error || "(bo'sh javob)"}
                          </pre>
                        </>
                      )}
                    </div>
                  ) : null}
                </Panel>
              </motion.div>
            );
          })}
        </div>
      )}
    </div>
  );
}
