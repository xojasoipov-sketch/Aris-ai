"use client";

/** Fayllar (/files) — Obsidian vault eslatmalari (Z47.2) + ZET xotirasi.
 *
 * ILGARI NIMA BO'LGAN. Sahifa `ComingSoon` placeholder edi va manba
 * sifatida "note.write/read/list (vault)" deb yozib qo'yilgandi. Bu
 * halol edi — soxta fayl ro'yxati chizilmagan. Lekin tool'lar
 * HAQIQATAN ishlayotgan edi: ZET eslatma yozardi va o'qirdi, ega esa
 * ularni interfeys orqali ko'ra olmasdi.
 *
 * Endi `GET /vault/notes` orqali haqiqiy eslatmalar ko'rinadi va
 * bosilsa matni ochiladi.
 *
 * XOTIRA BO'LIMI (yangi). ZET vault'dan tashqari uzoq muddatli
 * xotiraga (`POST /memory/search`, `GET /memory/layer/{layer}`) ham
 * yozadi — bu bo'lim ularni ko'rsatadi. Ikkinchi tab sifatida
 * qo'shildi (docs/13-XOTIRA-VA-ORGANISH.md): "Eslatmalar" — Obsidian
 * vault, "Xotira" — vektor xotira qatlamlari. Ikkalasi ham backend'ga
 * ulanadigan mustaqil manba, shu sabab bir sahifada aralashtirilmadi.
 */

import { Brain, FileText, Search, Video } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useRef, useState } from "react";

import { EmptyState } from "@/components/ui/forms";
import { Button, Eyebrow, Panel } from "@/components/ui/primitives";
import { Tabs } from "@/components/ui/Tabs";
import { api, type MemoryEntryDto, type Result } from "@/lib/api";
import { useResource } from "@/lib/useResource";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/* ── Eslatmalar (Obsidian vault) ──────────────────────────────── */

function NotesSection() {
  const [query, setQuery] = useState("");
  const [applied, setApplied] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  const list = useResource(() => api.notes(applied));
  const note = useResource(() => (open ? api.note(open) : Promise.resolve({ ok: true as const, data: { title: "", content: "" } })));

  const notes = list.state.kind === "ready" ? list.state.data.notes : [];

  return (
    <div className="space-y-5">
      <p className="text-sm text-[var(--text-secondary)]">
        {list.state.kind === "ready"
          ? `${list.state.data.total} ta eslatma · Obsidian vault`
          : list.state.kind === "loading"
            ? "Yuklanmoqda…"
            : "Backend bilan aloqa yo'q"}
      </p>

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

/* ── Xotira (Memory) ──────────────────────────────────────────── */

/** Qidiruv (`similarity` bor) va qatlam ro'yxati (`similarity` yo'q)
 * bitta ro'yxat sifatida ko'rsatiladi — shu sabab ikkalasi shu tipga
 * normallashtiriladi. */
interface MemoryListItem {
  entry: MemoryEntryDto;
  similarity: number | null;
}

const MEMORY_SEARCH_DEBOUNCE_MS = 400;
const MEMORY_SEARCH_MIN_CHARS = 2;
const DEFAULT_MEMORY_LAYER = "personal";

const MEMORY_LAYER_LABELS: Record<string, string> = {
  short_term: "qisqa muddat",
  conversation: "suhbat",
  task: "vazifa",
  project: "loyiha",
  business: "biznes",
  personal: "shaxsiy",
  knowledge: "bilim",
};

function isVideoLearnEntry(entry: MemoryEntryDto): boolean {
  return entry.source === "video.learn" || entry.tags.includes("video.learn");
}

function contentPreview(entry: MemoryEntryDto): string {
  const summary = entry.summary?.trim();
  if (summary) return summary;
  const content = entry.content.trim();
  if (!content) return "(bo'sh yozuv)";
  return content.length > 150 ? `${content.slice(0, 150)}…` : content;
}

/** `video.learn` chiqishi qat'iy JSON (docs/13 §3) — `content` shu
 * formatda saqlangan bo'lsa `gaps` massivini shu yerdan ajratamiz.
 * Parslab bo'lmasa yoki `gaps` maydoni yo'q bo'lsa — buni OCHIQ
 * bildiramiz, hech narsa o'ylab topilmaydi. */
function parseVideoGaps(content: string): string[] | null {
  try {
    const parsed: unknown = JSON.parse(content);
    if (
      parsed &&
      typeof parsed === "object" &&
      "gaps" in parsed &&
      Array.isArray((parsed as { gaps: unknown }).gaps)
    ) {
      return (parsed as { gaps: unknown[] }).gaps.filter(
        (g): g is string => typeof g === "string",
      );
    }
    return null;
  } catch {
    return null;
  }
}

function parseVideoTitle(content: string): string | null {
  try {
    const parsed: unknown = JSON.parse(content);
    if (parsed && typeof parsed === "object" && "title" in parsed) {
      const title = (parsed as { title: unknown }).title;
      return typeof title === "string" && title.trim() ? title.trim() : null;
    }
    return null;
  } catch {
    return null;
  }
}

function MemoryCard({ item, index }: { item: MemoryListItem; index: number }) {
  const { entry, similarity } = item;
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index, 10) * 0.03, duration: 0.3, ease: "easeOut" }}
    >
      <Panel className="p-4">
        <p className="text-sm text-[var(--text-primary)]">{contentPreview(entry)}</p>
        <div className="data mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-[var(--text-muted)]">
          <span>manba: {entry.source ?? "manba ko'rsatilmagan"}</span>
          <span>qatlam: {MEMORY_LAYER_LABELS[entry.layer] ?? entry.layer}</span>
          {similarity !== null ? <span>moslik: {Math.round(similarity * 100)}%</span> : null}
          <span>
            {entry.created_at
              ? new Date(entry.created_at).toLocaleDateString("uz-UZ")
              : "sana yo'q"}
          </span>
        </div>
      </Panel>
    </motion.div>
  );
}

function VideoLearnCard({ item, index }: { item: MemoryListItem; index: number }) {
  const { entry } = item;
  const gaps = parseVideoGaps(entry.content);
  const title = parseVideoTitle(entry.content) ?? contentPreview(entry);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index, 10) * 0.03, duration: 0.3, ease: "easeOut" }}
    >
      <Panel className="p-4">
        <div className="flex items-start gap-3">
          <Video
            size={16}
            strokeWidth={1.5}
            className="mt-0.5 shrink-0 text-[var(--text-muted)]"
            aria-hidden
          />
          <div className="min-w-0 flex-1">
            <p className="text-sm text-[var(--text-primary)]">{title}</p>
            <div className="data mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-[var(--text-muted)]">
              <span>
                {entry.created_at
                  ? new Date(entry.created_at).toLocaleDateString("uz-UZ")
                  : "sana yo'q"}
              </span>
            </div>
            <div className="mt-3">
              <Eyebrow>Bo&apos;shliqlar (gaps)</Eyebrow>
              {gaps === null ? (
                <p className="mt-1.5 text-xs text-[var(--text-muted)]">
                  gaps maydoni bu yozuvda topilmadi — content JSON sifatida saqlanmagan
                  yoki gaps kaliti yo&apos;q.
                </p>
              ) : gaps.length === 0 ? (
                <p className="mt-1.5 text-xs text-[var(--text-muted)]">
                  Video barcha savolga javob bergan — bo&apos;shliq topilmadi.
                </p>
              ) : (
                <ul className="mt-1.5 list-disc space-y-1 pl-4 text-xs leading-relaxed text-[var(--text-secondary)]">
                  {gaps.map((gap, i) => (
                    <li key={i}>{gap}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      </Panel>
    </motion.div>
  );
}

function MemorySection() {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const isFirstRun = useRef(true);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), MEMORY_SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [query]);

  const searching = debounced.length >= MEMORY_SEARCH_MIN_CHARS;

  const list = useResource<MemoryListItem[]>(() =>
    searching
      ? api.memory
          .search(debounced, { limit: 20 })
          .then(
            (res): Result<MemoryListItem[]> =>
              res.ok
                ? { ok: true, data: res.data.map((r) => ({ entry: r.entry, similarity: r.similarity })) }
                : res,
          )
      : api.memory
          .byLayer(DEFAULT_MEMORY_LAYER, 20)
          .then(
            (res): Result<MemoryListItem[]> =>
              res.ok
                ? { ok: true, data: res.data.map((e) => ({ entry: e, similarity: null })) }
                : res,
          ),
  );

  // `useResource` faqat mount'da yuklaydi (Z46.2 — reload() qo'lda
  // chaqiriladi). Qidiruv so'zi (debounce'dan keyin) o'zgarganda ro'yxatni
  // qayta o'qish shart — birinchi ishga tushishda buni o'tkazib yuboramiz,
  // chunki mount effekti allaqachon shu holat bilan bir marta yuklagan.
  useEffect(() => {
    if (isFirstRun.current) {
      isFirstRun.current = false;
      return;
    }
    void list.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced, searching]);

  const entries = list.state.kind === "ready" ? list.state.data : [];
  const videoEntries = entries.filter((item) => isVideoLearnEntry(item.entry));

  return (
    <div className="space-y-5">
      <p className="text-sm text-[var(--text-secondary)]">
        {searching
          ? list.state.kind === "ready"
            ? `${entries.length} ta natija · "${debounced}" bo'yicha semantik qidiruv`
            : list.state.kind === "loading"
              ? "Qidirilmoqda…"
              : "Backend bilan aloqa yo'q"
          : list.state.kind === "ready"
            ? `${entries.length} ta yozuv · so'nggi shaxsiy xotira`
            : list.state.kind === "loading"
              ? "Yuklanmoqda…"
              : "Backend bilan aloqa yo'q"}
      </p>

      <Panel className="p-3">
        <div className="flex items-center gap-2 rounded-[10px] border border-[var(--border-hairline)] bg-[var(--bg-base)] px-3">
          <Search size={15} strokeWidth={1.5} className="text-[var(--text-muted)]" aria-hidden />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Xotiradan qidirish… (kamida 2 belgi)"
            aria-label="Xotira qidirish"
            className="min-w-0 flex-1 bg-transparent py-2 text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)]"
          />
        </div>
      </Panel>

      {list.state.kind === "error" ? (
        <Panel className="p-4">
          <EmptyState
            title="Xotirani yuklab bo'lmadi"
            hint={list.state.message}
            action={
              <Button onClick={() => void list.reload()} variant="ghost">
                Qayta urinish
              </Button>
            }
          />
        </Panel>
      ) : null}

      {list.state.kind === "ready" && entries.length === 0 ? (
        <Panel className="p-4">
          <EmptyState
            icon={Brain}
            title={searching ? "Hech narsa topilmadi" : "Shaxsiy qatlamda yozuv yo'q"}
            hint={
              searching
                ? "Boshqa so'z bilan urinib ko'ring — moslik chegarasi past bo'lsa ham natija bo'lmasligi mumkin."
                : "ZET biror narsani PERSONAL qatlamga yozganda shu yerda ko'rinadi."
            }
          />
        </Panel>
      ) : null}

      {list.state.kind === "ready" && entries.length > 0 ? (
        <div className="space-y-2">
          {entries.map((item, i) => (
            <MemoryCard key={item.entry.id ?? `${item.entry.layer}-${i}`} item={item} index={i} />
          ))}
        </div>
      ) : null}

      {/* Video.learn bo'shliqlari — alohida kichik bo'lim (docs/13 §3).
          Yuqoridagi ro'yxatdan filtrlangan: alohida so'rov emas, chunki
          `source`/`tags` allaqachon shu yerda qo'lda mavjud. Bo'sh bo'lishi
          KUTILGAN holat — video.learn natijasi reja `memory` qadamini
          qo'shmasa umuman saqlanmaydi (docs/13-XOTIRA-VA-ORGANISH.md §4). */}
      {list.state.kind === "ready" ? (
        <div className="space-y-2 border-t border-[var(--border-hairline)] pt-5">
          <div className="flex items-center gap-2">
            <Video size={14} strokeWidth={1.5} className="text-[var(--text-muted)]" aria-hidden />
            <Eyebrow>Video.dan o&apos;rganilganlar</Eyebrow>
          </div>
          {videoEntries.length === 0 ? (
            <p className="text-xs text-[var(--text-muted)]">
              {searching
                ? "Bu qidiruv natijasida video.learn yozuvi topilmadi."
                : "Hali hech qanday video o'rganilmagan — yoki video.learn natijasi rejaga memory qadami sifatida saqlanmagan (docs/13-XOTIRA-VA-ORGANISH.md)."}
            </p>
          ) : (
            <div className="space-y-2">
              {videoEntries.map((item, i) => (
                <VideoLearnCard
                  key={item.entry.id ?? `video-${item.entry.layer}-${i}`}
                  item={item}
                  index={i}
                />
              ))}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

/* ── Sahifa ───────────────────────────────────────────────────── */

type FilesTab = "notes" | "memory";

export default function FilesPage() {
  const [tab, setTab] = useState<FilesTab>("notes");

  return (
    <div className="mx-auto max-w-4xl space-y-5 px-6 py-6 lg:px-8">
      <header>
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">Fayllar</h1>
        <p className="mt-0.5 text-sm text-[var(--text-secondary)]">
          Obsidian vault eslatmalari va ZET uzoq muddatli xotirasi
        </p>
      </header>

      <div className="flex">
        <Tabs
          tabs={["notes", "memory"] as const}
          value={tab}
          onChange={setTab}
          labels={{ notes: "Eslatmalar", memory: "Xotira" }}
        />
      </div>

      {tab === "notes" ? <NotesSection /> : <MemorySection />}
    </div>
  );
}
