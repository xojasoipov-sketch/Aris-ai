"use client";

/** App shell v2 — CLAUDE.md master tizim.
 * Chap sidebar (faol item: --accent-blue border-left), yuqori bar,
 * pastki FIXED status-bar (System Online · Uptime · Performance · vaqt).
 * Ikonlar: lucide-react, strokeWidth 1.5, 18px.
 */

import { AnimatePresence, motion } from "motion/react";
import {
  BarChart3,
  Bell,
  Bot,
  Calendar,
  Camera,
  FileText,
  FolderKanban,
  Hand,
  LayoutGrid,
  ListChecks,
  MessageSquare,
  MonitorSmartphone,
  Search,
  Settings,
  Terminal as TerminalIcon,
  Users,
  Volume2,
  VolumeX,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { ApprovalCard, KillSwitchButton } from "@/components/ui/devices";
import { Eyebrow } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { sound } from "@/lib/sound";
import { useBackendHealth } from "@/lib/useBackendHealth";
import { useResource } from "@/lib/useResource";

const NAV = [
  { href: "/", label: "Boshqaruv", icon: LayoutGrid },
  { href: "/nexus", label: "Nexus", icon: Hand },
  { href: "/ai-chat", label: "AI Yordamchi", icon: Bot },
  { href: "/agents", label: "Agentlar", icon: Users },
  { href: "/tizim", label: "TIZIM", icon: Workflow },
  { href: "/projects", label: "Loyihalar", icon: FolderKanban },
  { href: "/calendar", label: "Taqvim", icon: Calendar },
  { href: "/tasks", label: "Vazifalar", icon: ListChecks },
  { href: "/messages", label: "Xabarlar", icon: MessageSquare },
  { href: "/files", label: "Fayllar", icon: FileText },
  { href: "/analytics", label: "Analitika", icon: BarChart3 },
  { href: "/devices", label: "Qurilmalar", icon: MonitorSmartphone },
  { href: "/camera", label: "Kamera", icon: Camera },
  { href: "/terminal", label: "Terminal", icon: TerminalIcon },
  { href: "/settings", label: "Sozlamalar", icon: Settings },
] as const;

/* Pastki status-bar uchun jonli soat + uptime */
function useNow() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return now;
}

function useUptime() {
  const [start] = useState(() => Date.now());
  const now = useNow();
  if (!now) return "00:00:00";
  const s = Math.floor((now.getTime() - start) / 1000);
  const h = String(Math.floor(s / 3600)).padStart(2, "0");
  const m = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const sec = String(s % 60).padStart(2, "0");
  return `${h}:${m}:${sec}`;
}

/** Favqulodda to'xtatish holati — devices/page.tsx dagi naqshning AYNAN
 * o'zi (5s poll GET /killswitch, engage/disengage POST). AppShell darajasida
 * qurilgani uchun StatusBar VA mobil pastki tugma bir xil holatni ulashadi. */
function useKillswitchState() {
  const [engaged, setEngaged] = useState(false);
  const [backendOk, setBackendOk] = useState(false);

  useEffect(() => {
    let alive = true;
    const check = async () => {
      const res = await api.killswitch.status();
      if (!alive) return;
      if (res.ok) {
        setBackendOk(true);
        setEngaged(res.data.engaged);
      }
    };
    void check();
    const t = setInterval(() => void check(), 5000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const engage = async () => {
    setEngaged(true);
    if (backendOk) await api.killswitch.engage();
  };
  const disengage = async () => {
    setEngaged(false);
    if (backendOk) await api.killswitch.disengage();
    sound.play("success");
  };

  return { engaged, engage, disengage };
}

function SoundToggle() {
  const [on, setOn] = useState(true);
  useEffect(() => setOn(sound.enabled), []);
  return (
    <button
      aria-label={on ? "Ovozni o'chirish" : "Ovozni yoqish"}
      className="rounded-lg p-2 text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]"
      onClick={() => {
        const next = !on;
        sound.setEnabled(next);
        setOn(next);
        if (next) sound.play("tick");
      }}
    >
      {on ? <Volume2 size={18} strokeWidth={1.5} /> : <VolumeX size={18} strokeWidth={1.5} />}
    </button>
  );
}

/** Global tasdiqlash badge — har sahifada ko'rinadi (AppShell hammasini
 * o'rab turgani uchun shu yerga qo'shish yetarli). `api.approvals.listAll()`
 * ni 10s'da so'raydi (Z46.2 `useResource` naqshi), qo'ng'iroq ikonkasi
 * ustida sonlar badge — kutilayotgan tasdiq = ogohlantiruvchi rang
 * (--status-working), xato emas. */
function ApprovalsBadge() {
  const { state, reload } = useResource(() => api.approvals.listAll(), 10_000);
  const [open, setOpen] = useState(false);
  const approvals = state.kind === "ready" ? state.data : [];

  const approve = async (id: string) => {
    const res = await api.approvals.approve(id);
    if (res.ok) void reload();
  };
  const reject = async (id: string) => {
    const res = await api.approvals.reject(id);
    if (res.ok) void reload();
  };

  return (
    <div className="relative">
      <button
        aria-label={`Kutilayotgan tasdiqlar${approvals.length > 0 ? ` (${approvals.length})` : ""}`}
        onClick={() => setOpen((o) => !o)}
        className="relative rounded-lg p-2 text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]"
      >
        <Bell size={18} strokeWidth={1.5} />
        {approvals.length > 0 ? (
          <span
            className="data absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-semibold text-[#050608]"
            style={{ background: "var(--status-working)" }}
          >
            {approvals.length}
          </span>
        ) : null}
      </button>

      <AnimatePresence>
        {open ? (
          <>
            {/* Tashqariga bosilganda yopish uchun shaffof qoplama —
                KillSwitchButton'dagi modal naqshi bilan bir xil. */}
            <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ type: "spring", stiffness: 300, damping: 30 }}
              className="floating absolute right-0 top-full z-50 mt-2 max-h-[70vh] w-80 overflow-y-auto p-4"
            >
              <Eyebrow>Kutilayotgan tasdiqlar</Eyebrow>
              {state.kind === "error" ? (
                <p className="mt-3 text-xs text-[var(--status-alert)]">{state.message}</p>
              ) : approvals.length === 0 ? (
                <p className="mt-3 text-xs text-[var(--text-muted)]">Kutilayotgan tasdiq yo'q</p>
              ) : (
                <div className="mt-3 space-y-3">
                  {approvals.map((a) => (
                    <ApprovalCard
                      key={a.id}
                      approval={{
                        id: a.id,
                        toolName: a.tool_name ?? "?",
                        reason: a.reason,
                        // ApprovalDto'da preview maydoni YO'Q (backend hali
                        // qaytarmaydi) — shu sabab bo'sh obyekt, ApprovalCard
                        // preview bloki bo'sh bo'lsa uni chizmaydi.
                        preview: {},
                        expiresAt: a.expires_at,
                      }}
                      onApprove={approve}
                      onReject={reject}
                    />
                  ))}
                </div>
              )}
            </motion.div>
          </>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

/* Mobil bottom-tab-bar — sidebar lg dan past ekranlarda shu bilan almashadi */
function MobileTabBar({ pathname }: { pathname: string }) {
  // Manzil bo'yicha tanlanadi, INDEKS bo'yicha emas: ilgari
  // `[NAV[0], NAV[1], NAV[5], ...]` edi va `NAV` ga o'rtadan bitta
  // qator qo'shilishi mobil tablarni jimgina boshqa sahifalarga
  // ko'chirib yuborardi.
  const MOBILE = ["/", "/nexus", "/tizim", "/tasks", "/analytics"];
  const TABS = MOBILE.map((href) => NAV.find((item) => item.href === href)).filter(
    (item): item is (typeof NAV)[number] => item !== undefined,
  );
  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 flex items-stretch justify-around border-t border-[var(--border-hairline)] bg-[var(--bg-elevated)] lg:hidden">
      {TABS.map(({ href, label, icon: I }) => {
        const active = pathname === href;
        return (
          <Link
            key={href}
            href={href}
            className={`flex flex-1 flex-col items-center gap-0.5 border-t-2 py-2 text-[10px] ${
              active
                ? "border-[var(--accent-blue)] text-[var(--text-primary)]"
                : "border-transparent text-[var(--text-muted)]"
            }`}
          >
            <I size={18} strokeWidth={1.5} className={active ? "text-[var(--accent-blue)]" : ""} />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

function StatusBar() {
  const now = useNow();
  const uptime = useUptime();
  const health = useBackendHealth();
  const { engaged, engage, disengage } = useKillswitchState();

  const healthMeta =
    health === "online"
      ? { color: "var(--status-online)", text: "Tizim onlayn", pulse: false }
      : health === "offline"
        ? { color: "var(--status-offline)", text: "Backend ulanmagan", pulse: false }
        : { color: "var(--status-working)", text: "Tekshirilmoqda…", pulse: true };

  return (
    <>
      <footer
        className={`fixed inset-x-0 bottom-0 z-40 hidden items-center justify-between border-t px-6 py-1.5 text-xs lg:flex ${
          engaged
            ? "border-[var(--status-alert)] bg-[rgba(239,68,68,0.08)]"
            : "border-[var(--border-hairline)] bg-[var(--bg-elevated)]"
        }`}
      >
        <div className="flex items-center gap-5">
          <div className="flex items-center gap-2">
            <span
              className={`inline-block h-1.5 w-1.5 rounded-full ${healthMeta.pulse ? "pulse-dot" : ""}`}
              style={{ background: healthMeta.color }}
            />
            <span className="text-[var(--text-secondary)]">{healthMeta.text}</span>
          </div>
          <KillSwitchButton engaged={engaged} onEngage={engage} onDisengage={disengage} />
        </div>
        <div className="data flex items-center gap-6 text-[var(--text-muted)]">
          <span>
            Sessiya <span className="text-[var(--text-secondary)]">{uptime}</span>
          </span>
          <span className="text-[var(--text-secondary)]">
            {now
              ? `${now.toLocaleDateString("uz-UZ", { day: "2-digit", month: "2-digit", year: "numeric" })} · ${now.toLocaleTimeString("uz-UZ", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`
              : ""}
          </span>
        </div>
      </footer>

      {/* Mobil: killswitch StatusBar'dan TASHQARIDA, alohida fixed
          burchakda — favqulodda to'xtatish ekran hajmidan qat'iy nazar
          doim ko'rinishi kerak (StatusBar o'zi `lg:flex` bilan yashirin,
          bu yerda esa `lg:hidden` — desktopda takrorlanmasin). */}
      <div className="fixed bottom-16 right-3 z-40 max-w-[85vw] lg:hidden">
        <KillSwitchButton engaged={engaged} onEngage={engage} onDisengage={disengage} />
      </div>
    </>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [search, setSearch] = useState("");

  return (
    <div className="flex min-h-screen">
      {/* ── Sidebar ── */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-56 flex-col border-r border-[var(--border-hairline)] bg-[var(--bg-elevated)] pb-9 lg:flex">
        {/* ZET wordmark — nuqtali halqa logo */}
        <Link href="/" className="flex items-center gap-3 px-5 py-5">
          <svg width="26" height="26" viewBox="0 0 28 28" aria-hidden>
            {Array.from({ length: 20 }, (_, i) => {
              const a = (i / 20) * Math.PI * 2;
              return (
                <circle
                  key={i}
                  cx={14 + 10 * Math.cos(a)}
                  cy={14 + 10 * Math.sin(a)}
                  r="0.9"
                  fill="var(--accent-blue)"
                  opacity={0.35 + 0.65 * ((i % 5) / 5)}
                />
              );
            })}
          </svg>
          <span className="text-base font-semibold tracking-[0.25em] text-[var(--text-primary)]">
            ZET
          </span>
        </Link>

        <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-4">
          {NAV.map(({ href, label, icon: I }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                className={`flex items-center gap-3 border-l-2 py-2 pl-3.5 pr-3 text-sm transition-colors ${
                  active
                    ? "border-[var(--accent-blue)] bg-[var(--surface-hover)] text-[var(--text-primary)]"
                    : "border-transparent text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]"
                }`}
              >
                <I
                  size={18}
                  strokeWidth={1.5}
                  className={active ? "text-[var(--accent-blue)]" : ""}
                />
                {label}
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-[var(--border-hairline)] px-5 py-3.5">
          <div className="flex items-center gap-2.5">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--status-online)]" />
            <div>
              <div className="text-sm text-[var(--text-primary)]">Ega</div>
              <div className="text-[11px] text-[var(--text-muted)]">Onlayn</div>
            </div>
          </div>
        </div>
      </aside>

      {/* ── Asosiy qism ── */}
      <div className="flex min-h-screen flex-1 flex-col pb-16 lg:ml-56 lg:pb-9">
        <header className="sticky top-0 z-30 flex items-center justify-between gap-6 border-b border-[var(--border-hairline)] bg-[rgba(5,6,8,0.85)] px-8 py-3">
          {/* Qidiruv — ENTER bosilganda ZET'ga buyruq sifatida ketadi.
              Ilgari bu maydon `value`/`onChange`siz edi: yozib bo'lardi,
              lekin hech qayerga bormasdi — bezak input. */}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const q = search.trim();
              if (!q) return;
              setSearch("");
              router.push(`/messages?q=${encodeURIComponent(q)}`);
            }}
            className="flex max-w-md flex-1 items-center gap-2.5 rounded-full border border-[var(--border-hairline)] bg-[var(--bg-elevated)] px-4 py-2"
          >
            <Search size={16} strokeWidth={1.5} className="text-[var(--text-muted)]" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="ZET'ga buyruq yozing…"
              aria-label="ZET'ga buyruq"
              className="w-full bg-transparent text-sm text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)]"
            />
          </form>
          <div className="flex items-center gap-1">
            <ApprovalsBadge />
            <SoundToggle />
          </div>
        </header>
        <main className="flex-1">{children}</main>
      </div>

      <StatusBar />
      <MobileTabBar pathname={pathname} />
    </div>
  );
}
