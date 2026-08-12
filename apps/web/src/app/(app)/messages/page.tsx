"use client";

/** Xabarlar (/messages) — HAQIQIY suhbat tarixi (Z47.1).
 *
 * ILGARI NIMA BO'LGAN — bu sahifadagi eng jiddiy nuqson edi:
 *
 *   · To'rtta TO'LIQ o'ylab topilgan suhbat ko'rsatilardi, o'ylab
 *     topilgan vaqt tamg'alari va mazmun bilan ("PR #42 ko'rib
 *     chiqildi, CI yashil", "Weekly Strategy Report, 2.4 MB").
 *   · Yozish maydoni ISHLAYOTGANDEK ko'rinardi (bo'sh bo'lsa tugma
 *     o'chardi), lekin yuborish matnni SHUNCHAKI TASHLAB YUBORARDI:
 *     ro'yxatga qo'shilmasdi, backend'ga ketmasdi. Ega yozgan har bir
 *     xabar jimgina yo'qolardi.
 *
 * Endi tarix `GET /conversations/web/messages` dan o'qiladi, yuborish
 * esa `POST /run` orqali ketadi va javob saqlanadi.
 */

import { CornerDownLeft, Loader2, MessageSquare } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useRef, useState } from "react";

import { EmptyState } from "@/components/ui/forms";
import { Button, Eyebrow, Panel } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { sound } from "@/lib/sound";
import { useResource } from "@/lib/useResource";

const CHANNEL = "web";

export default function MessagesPage() {
  const { state, reload } = useResource(() => api.messages(CHANNEL));
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const messages = state.kind === "ready" ? state.data : [];

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages.length, sending]);

  const send = async () => {
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true);
    setDraft("");

    const res = await api.run(text, CHANNEL);
    if (!res.ok) sound.play("error");
    // Muvaffaqiyat ham, xato ham — tarixni qayta o'qiymiz: backend
    // savolni saqlab, javobda yiqilgan bo'lishi mumkin.
    await reload();
    setSending(false);
  };

  return (
    <div className="mx-auto flex h-[calc(100vh-8.5rem)] max-w-3xl flex-col px-6 py-4">
      <header className="pb-3">
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">Xabarlar</h1>
        <p className="mt-0.5 text-sm text-[var(--text-secondary)]">
          {state.kind === "ready"
            ? `${messages.length} ta xabar · veb kanali`
            : state.kind === "loading"
              ? "Yuklanmoqda…"
              : "Backend bilan aloqa yo'q"}
        </p>
      </header>

      <Panel className="flex min-h-0 flex-1 flex-col overflow-hidden p-0">
        <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
          {state.kind === "error" ? (
            <EmptyState
              title="Tarixni yuklab bo'lmadi"
              hint={state.message}
              action={
                <Button onClick={() => void reload()} variant="ghost">
                  Qayta urinish
                </Button>
              }
            />
          ) : null}

          {state.kind === "ready" && messages.length === 0 ? (
            <EmptyState
              icon={MessageSquare}
              title="Suhbat hali boshlanmagan"
              hint="Pastdan yozing — ZET javobi shu yerda saqlanadi va keyingi safar eslab qoladi."
            />
          ) : null}

          {messages.map((message, i) => (
            <motion.div
              key={message.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Math.min(i, 8) * 0.02, duration: 0.25 }}
              className={message.role === "user" ? "flex justify-end" : "flex justify-start"}
            >
              <div
                className={`max-w-[80%] rounded-[14px] px-3.5 py-2.5 text-sm leading-relaxed ${
                  message.role === "user"
                    ? "bg-[var(--accent-blue)] text-[#050608]"
                    : "border border-[var(--border-hairline)] bg-[var(--bg-base)] text-[var(--text-primary)]"
                }`}
              >
                {message.content}
                <div
                  className={`data mt-1 text-[10px] ${
                    message.role === "user" ? "text-[#050608]/60" : "text-[var(--text-muted)]"
                  }`}
                >
                  {new Date(message.created_at).toLocaleTimeString("uz-UZ", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </div>
              </div>
            </motion.div>
          ))}

          {sending ? (
            <div className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
              <Loader2 size={13} strokeWidth={1.5} className="animate-spin" aria-hidden />
              ZET javob yozmoqda…
            </div>
          ) : null}
        </div>

        <div className="flex items-center gap-2 border-t border-[var(--border-hairline)] px-3 py-3">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            disabled={sending}
            placeholder="Xabar yozing…"
            aria-label="Xabar matni"
            className="min-w-0 flex-1 rounded-[10px] border border-[var(--border-hairline)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)] focus-visible:border-[var(--border-active)] disabled:opacity-50"
          />
          <Button
            onClick={() => void send()}
            disabled={!draft.trim() || sending}
            variant="primary"
            aria-label="Yuborish"
          >
            {sending ? (
              <Loader2 size={16} strokeWidth={1.5} className="animate-spin" aria-hidden />
            ) : (
              <CornerDownLeft size={16} strokeWidth={1.5} aria-hidden />
            )}
          </Button>
        </div>
      </Panel>

      <p className="pt-2 text-center text-[10px] text-[var(--text-muted)]">
        <Eyebrow>Tarix saqlanadi — ZET oldingi gapni eslaydi</Eyebrow>
      </p>
    </div>
  );
}
