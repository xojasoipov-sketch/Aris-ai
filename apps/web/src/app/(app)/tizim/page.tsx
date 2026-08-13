"use client";

/** TIZIM (/tizim) — 6 tayyor avtomatlashtirish (Z48).
 *
 * NEGA BU SAHIFA KERAK BO'LDI.
 *
 * Ega yuborgan slaydlarning YURAGI aynan shu oltita retsept edi
 * ("Uchrashuv kotibi", "Kunlik puls" va h.k.) — va'da esa bir qatorlik:
 *
 *     "Sizga qoladi: faqat qaror qabul qilish."
 *
 * Backend ularni Z40'da qurdi va `GET /automation/recipes` ochib
 * bergandi. Lekin INTERFEYSDA ular umuman yo'q edi: ega qaysi retsept
 * tayyorligini ko'ra olmasdi va hech qaysisini yoqa olmasdi. Ya'ni
 * mahsulotning eng muhim qismi faqat API'da yashab turgandi.
 *
 * HALOL HOLAT — bu sahifaning asosiy qoidasi. Imkoniyati yetishmagan
 * retsept "yoqish" tugmasini KO'RSATMAYDI va aynan nima yetishmayotgani
 * yozib qo'yiladi. Chala ishlaydigan avtomatlashtirish umuman yo'q
 * avtomatlashtirishdan yomonroq: ega uchrashuv qo'yilgan deb o'ylab,
 * kalendarni tekshirmay qolardi.
 */

import { AlertTriangle, Check, Clock, Zap } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";

import { EmptyState } from "@/components/ui/forms";
import { Button, Eyebrow, Panel, StatusDot } from "@/components/ui/primitives";
import { api, type RecipeDto } from "@/lib/api";
import { sound } from "@/lib/sound";
import { useResource } from "@/lib/useResource";

/** Imkoniyat kodini ega tushunadigan gapga o'giradi.
 *
 * Backend `meeting_link` deb yuboradi — bu dasturchi tili. Ega esa
 * NIMA QILISH KERAKLIGINI bilishi kerak, shuning uchun har biriga
 * "nimaga tayanadi" izohi yoziladi. */
const CAPABILITY_LABELS: Record<string, string> = {
  llm: "Til modeli",
  cron: "Vaqt jadvali",
  "telegram.send": "Telegram yuborish",
  "telegram.read_groups": "Telegram guruh tarixini o'qish (MTProto sessiyasi kerak)",
  calendar: "Kalendar",
  meeting_link: "Uchrashuv havolasi (Zoom/Meet API kerak)",
  stt: "Ovozdan matnga (ElevenLabs kaliti kerak)",
  "content.publish": "Kontent chop etish",
  "instagram.webhook": "Instagram izoh/Direct obunasi kerak",
  crm: "Mijozlar bazasi",
  task_board: "Vazifa doskasi",
  // B2 (KONSOLIDATSIYA v2): "approval.timed" ("sukut = rozilik"
  // taymerli tasdiq) BUTUNLAY OLIB TASHLANDI — V-32'ga zid edi.
  // Kontent nashri endi oddiy tasdiq (ApprovalService) orqali ishlaydi.
};

/** Cron ifodasini soatga o'giradi: "20 9 * * *" → "09:20".
 *
 * To'liq cron parseri EMAS va bo'lishi ham shart emas: retseptlarning
 * hammasi oddiy "har kuni soat X" jadvali. Murakkabroq ifoda kelsa
 * xom matn ko'rsatiladi — noto'g'ri vaqt ko'rsatishdan ko'ra yaxshiroq. */
function cronToTime(expr: string): string {
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return expr;
  const [minute, hour, dom, month, dow] = parts;
  if (dom !== "*" || month !== "*" || dow !== "*") return expr;
  if (!/^\d+$/.test(minute) || !/^\d+$/.test(hour)) return expr;
  return `${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`;
}

function triggerText(recipe: RecipeDto): string {
  if (recipe.trigger_kind === "time") {
    const times = [recipe.trigger_spec, ...recipe.also_at].map(cronToTime);
    return `Har kuni ${times.join(" va ")}`;
  }
  return "Hodisa yuz berganda";
}

export default function TizimPage() {
  const { state, reload } = useResource(() => api.recipes.list());
  const schedules = useResource(() => api.schedules());
  const [busy, setBusy] = useState<string | null>(null);
  const [failed, setFailed] = useState<Record<string, string>>({});

  const recipes = state.kind === "ready" ? state.data : [];
  const readyCount = recipes.filter((r) => r.status === "ready").length;

  // O'rnatilgan jadvallar nomi "T06 · Kunlik puls" ko'rinishida —
  // shundan retsept kodini ajratib olamiz. Backend'da retsept ↔ qoida
  // bog'lanishi saqlanmaydi, shuning uchun nom yagona bog'lovchi.
  const installedCodes = new Set(
    (schedules.state.kind === "ready" ? schedules.state.data : [])
      .map((rule) => rule.name.split("·")[0]?.trim())
      .filter(Boolean),
  );

  const install = async (code: string) => {
    setBusy(code);
    setFailed((prev) => {
      const next = { ...prev };
      delete next[code];
      return next;
    });

    const res = await api.recipes.install(code);
    if (!res.ok) {
      sound.play("error");
      setFailed((prev) => ({ ...prev, [code]: res.error }));
    }
    await Promise.all([reload(), schedules.reload()]);
    setBusy(null);
  };

  return (
    <div className="mx-auto max-w-4xl space-y-5 px-6 py-6 lg:px-8">
      <header>
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">TIZIM</h1>
        <p className="mt-0.5 text-sm text-[var(--text-secondary)]">
          {state.kind === "ready"
            ? `${recipes.length} ta avtomatlashtirish · ${readyCount} tasi tayyor`
            : state.kind === "loading"
              ? "Yuklanmoqda…"
              : "Backend bilan aloqa yo'q"}
        </p>
        <p className="mt-2 max-w-xl text-xs leading-relaxed text-[var(--text-muted)]">
          Sizga qoladi: faqat qaror qabul qilish. Qolgani — yozish, tekshirish, eslatish, chop
          etish — tizimda.
        </p>
      </header>

      {state.kind === "error" ? (
        <Panel className="p-4">
          <EmptyState
            title="Retseptlarni yuklab bo'lmadi"
            hint={state.message}
            action={
              <Button onClick={() => void reload()} variant="ghost">
                Qayta urinish
              </Button>
            }
          />
        </Panel>
      ) : null}

      <div className="space-y-3">
        {recipes.map((recipe, i) => {
          const ready = recipe.status === "ready";
          const installed = installedCodes.has(recipe.code);

          return (
            <motion.div
              key={recipe.code}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Math.min(i, 6) * 0.04, duration: 0.3, ease: "easeOut" }}
            >
              <Panel className="p-5">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="data text-[11px] text-[var(--text-muted)]">
                        {recipe.code}
                      </span>
                      <StatusDot
                        color={
                          ready ? "var(--status-online)" : "var(--status-offline)"
                        }
                      />
                      <h2 className="truncate text-sm font-medium text-[var(--text-primary)]">
                        {recipe.name}
                      </h2>
                    </div>
                    <p className="mt-1 text-xs leading-relaxed text-[var(--text-secondary)]">
                      {recipe.promise}
                    </p>
                  </div>

                  {ready ? (
                    installed ? (
                      <span className="flex shrink-0 items-center gap-1.5 rounded-full border border-[var(--border-hairline)] px-3 py-1 text-[11px] text-[var(--status-online)]">
                        <Check size={12} strokeWidth={1.5} aria-hidden />
                        Yoqilgan
                      </span>
                    ) : (
                      <Button
                        variant="primary"
                        onClick={() => void install(recipe.code)}
                        disabled={busy === recipe.code}
                        className="shrink-0"
                      >
                        {busy === recipe.code ? "Yoqilmoqda…" : "Yoqish"}
                      </Button>
                    )
                  ) : (
                    <span className="shrink-0 rounded-full border border-[var(--border-hairline)] px-3 py-1 text-[11px] text-[var(--text-muted)]">
                      Tayyor emas
                    </span>
                  )}
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[var(--text-muted)]">
                  <span className="flex items-center gap-1.5">
                    {recipe.trigger_kind === "time" ? (
                      <Clock size={12} strokeWidth={1.5} aria-hidden />
                    ) : (
                      <Zap size={12} strokeWidth={1.5} aria-hidden />
                    )}
                    {triggerText(recipe)}
                  </span>
                </div>

                <ol className="mt-3 space-y-1.5">
                  {recipe.steps.map((step) => {
                    const blocked = recipe.blocked_steps.includes(Number(step.order));
                    return (
                      <li
                        key={step.order}
                        className={`flex gap-2.5 text-xs ${
                          blocked ? "text-[var(--text-muted)]" : "text-[var(--text-secondary)]"
                        }`}
                      >
                        <span className="data shrink-0 text-[var(--text-muted)]">
                          {step.order}
                        </span>
                        <span className="min-w-0">
                          {step.title}
                          {blocked ? " — bu qadam bajarilmaydi" : ""}
                        </span>
                      </li>
                    );
                  })}
                </ol>

                <div className="mt-3 border-t border-[var(--border-hairline)] pt-3">
                  <Eyebrow>Natija</Eyebrow>
                  <p className="mt-1 text-xs text-[var(--text-secondary)]">{recipe.result}</p>
                </div>

                {recipe.missing.length > 0 ? (
                  <div className="mt-3 flex gap-2 rounded-[10px] border border-[var(--border-hairline)] bg-[var(--bg-base)] px-3 py-2.5">
                    <AlertTriangle
                      size={13}
                      strokeWidth={1.5}
                      className="mt-0.5 shrink-0 text-[var(--status-working)]"
                      aria-hidden
                    />
                    <div className="min-w-0 text-[11px] leading-relaxed text-[var(--text-muted)]">
                      Yetishmaydi:{" "}
                      {recipe.missing
                        .map((key) => CAPABILITY_LABELS[key] ?? key)
                        .join(" · ")}
                    </div>
                  </div>
                ) : null}

                {failed[recipe.code] ? (
                  <p className="mt-2 text-[11px] text-[var(--status-alert)]">
                    Yoqib bo'lmadi: {failed[recipe.code]}
                  </p>
                ) : null}
              </Panel>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
