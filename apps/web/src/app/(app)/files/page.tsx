"use client";

/** Fayllar (/files) — Obsidian vault eslatmalari (Z47.2).
 *
 * ILGARI NIMA BO'LGAN. Sahifa `ComingSoon` placeholder edi va manba
 * sifatida "note.write/read/list (vault)" deb yozib qo'yilgandi. Bu
 * halol edi — soxta fayl ro'yxati chizilmagan. Lekin tool'lar
 * HAQIQATAN ishlayotgan edi: ZET eslatma yozardi va o'qirdi, ega esa
 * ularni interfeys orqali ko'ra olmasdi.
 *
 * Endi `GET /vault/notes` orqali haqiqiy eslatmalar ko'rinadi va
 * bosilsa matni ochiladi.
 */

import { FileText, Search } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";

import { EmptyState } from "@/components/ui/forms";
import { Button, Eyebrow, Panel } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function FilesPage() {
  const [query, setQuery] = useState("");
  const [applied, setApplied] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  const list = useResource(() => api.notes(applied));
  const note = useResource(() => (open ? api.note(open) : Promise.resolve({ ok: true as const, data: { title: "", content: "" } })));

  const notes = list.state.kind === "ready" ? list.state.data.notes : [];

  return (
    <div className="mx-auto max-w-4xl space-y-5 px-6 py-6 lg:px-8">
      <header>
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">Fayllar</h1>
        <p className="mt-0.5 text-sm text-[var(--text-secondary)]">
          {list.state.kind === "ready"
            ? `${list.state.data.total} ta eslatma · Obsidian vault`
            : list.state.kind === "loading"
              ? "Yuklanmoqda…"
              : "Backend bilan aloqa yo'q"}
        </p>
      </header>

      <Panel className="p-3">
        <div className="flex gap-2">
          <div className="flex flex-1 items-center gap-2 rounded-[10px] border border-[var(--border-hairline)] bg-[var(--bg-base)] px-3">
            <Search size={15} strokeWidth={1.5} className="text-[var(--text-muted)]" aria-hidden />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") setApplied(query.trim());
              }}
              placeholder="Eslatma ichidan qidirish…"
              aria-label="Eslatma qidirish"
              className="min-w-0 flex-1 bg-transparent py-2 text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)]"
            />
          </div>
          <Button onClick={() => setApplied(query.trim())} variant="primary">
            Qidirish
          </Button>
        </div>
      </Panel>

      {list.state.kind === "error" ? (
        <Panel className="p-4">
          <EmptyState
            title="Eslatmalarni yuklab bo'lmadi"
            hint={list.state.message}
            action={
              <Button onClick={() => void list.reload()} variant="ghost">
                Qayta urinish
              </Button>
            }
          />
        </Panel>
      ) : null}

      {list.state.kind === "ready" && notes.length === 0 ? (
        <Panel className="p-4">
          <EmptyState
            icon={FileText}
            title={applied ? "Hech narsa topilmadi" : "Vault bo'sh"}
            hint={
              applied
                ? "Boshqa so'z bilan urinib ko'ring."
                : "ZET eslatma yozganda ular shu yerda ko'rinadi."
            }
          />
        </Panel>
      ) : null}

      <div className="space-y-2">
        {notes.map((item, i) => (
          <motion.div
            key={item.title}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: Math.min(i, 10) * 0.03, duration: 0.3, ease: "easeOut" }}
          >
            <Panel className="overflow-hidden p-0">
              <button
                onClick={() => setOpen(open === item.title ? null : item.title)}
                aria-expanded={open === item.title}
                className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-[var(--surface-hover)]"
              >
                <FileText
                  size={16}
                  strokeWidth={1.5}
                  className="shrink-0 text-[var(--text-muted)]"
                  aria-hidden
                />
                <span className="min-w-0 flex-1 truncate text-sm text-[var(--text-primary)]">
                  {item.title}
                </span>
                <span className="data shrink-0 text-[10px] text-[var(--text-muted)]">
                  {formatSize(item.size_bytes)}
                </span>
                <span className="data hidden shrink-0 text-[10px] text-[var(--text-muted)] sm:block">
                  {new Date(item.modified_at * 1000).toLocaleDateString("uz-UZ")}
                </span>
              </button>

              {open === item.title ? (
                <div className="border-t border-[var(--border-hairline)] px-4 py-3">
                  <Eyebrow>Mazmun</Eyebrow>
                  <pre className="mt-2 max-h-72 overflow-auto text-xs leading-relaxed whitespace-pre-wrap text-[var(--text-secondary)]">
                    {note.state.kind === "ready"
                      ? note.state.data.content || "(bo'sh)"
                      : note.state.kind === "loading"
                        ? "Yuklanmoqda…"
                        : "O'qib bo'lmadi"}
                  </pre>
                </div>
              ) : null}
            </Panel>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
