/** ZET backend client — /api/zet/* proksi orqali (route handler).
 *
 * Muhim qoidalar:
 *   - Backend o'chiq bo'lsa UI yiqilmaydi — har chaqiruv Result qaytaradi
 *   - Soxta ma'lumot YO'Q: sahifa faqat backend bergan narsani ko'rsatadi
 *
 * Tiplar REAL kontraktga mos (jonli backend'da tekshirilgan):
 *   GET  /approvals[?run_id=…]          → ApprovalDto[]  (run_id IXTIYORIY —
 *        berilsa shu run'ga tegishlilari, berilmasa BARCHA kutilayotganlar)
 *   POST /approvals/{id}/approve|reject → body {note?} MAJBURIY (bo'sh {} ham bo'ladi)
 *   GET  /killswitch                    → {killswitch: {...}} (ichma-ich — unwrap qilamiz)
 *   POST /killswitch/engage             → body {reason} MAJBURIY
 *   GET  /health                        → {status}
 *   GET  /system                        → o'lchangan CPU/RAM/disk (Z46.1)
 *   GET  /integrations                  → tekshirilgan xizmat holati (Z46.1)
 *   CRUD /projects /tasks /events       → ish maydoni (Z46)
 *   GET  /runs?limit=&offset=           → RunHistoryDto[] (run tarixi, DB'dan)
 *   POST /memory/search                 → MemorySearchResultDto[]
 *   GET  /memory/layer/{layer}?limit=   → MemoryEntryDto[]
 *   POST /memory/ingest-profile         → multipart "file" → {sections_found,
 *        added, failed, errors} (Content-Type qo'lda QO'YILMAYDI — brauzer
 *        o'zi boundary bilan qo'yadi, quyidagi `call()` buni FormData orqali biladi)
 */

export type Result<T> = { ok: true; data: T } | { ok: false; error: string };

async function call<T>(path: string, init?: RequestInit): Promise<Result<T>> {
  try {
    // FormData (masalan fayl-yuklash) uchun "Content-Type" QO'LDA QO'YILMAYDI —
    // brauzer o'zi to'g'ri "multipart/form-data; boundary=…" ni qo'shadi.
    // Qo'lda "application/json" majburlansa, boundary yo'qoladi va backend
    // multipart tanani parslay olmaydi.
    const isFormData = init?.body instanceof FormData;
    const headers = isFormData
      ? { ...init?.headers }
      : { "Content-Type": "application/json", ...init?.headers };
    const res = await fetch(`/api/zet${path}`, {
      ...init,
      headers,
    });
    if (!res.ok) {
      return { ok: false, error: `HTTP ${res.status}` };
    }
    // 204 No Content — tanasi BO'SH. `res.json()` bunda istisno
    // otadi va DELETE muvaffaqiyatli bo'lsa ham xato ko'rinardi.
    if (res.status === 204) {
      return { ok: true, data: undefined as T };
    }
    return { ok: true, data: (await res.json()) as T };
  } catch {
    return { ok: false, error: "Backend bilan aloqa yo'q" };
  }
}

/* ── Tiplar (backend route sxemalari bilan AYNAN mos) ──────────── */

export interface ApprovalDto {
  id: string;
  run_id: string;
  status: string;
  reason: string;
  tool_name: string | null;
  requested_permission: string;
  created_at: string;
  expires_at: string;
}

export interface ApprovalDecisionDto {
  approval: ApprovalDto;
  run_id: string;
  run_status: string;
}

export interface KillswitchDto {
  engaged: boolean;
  reason: string | null;
  engaged_at: string | null;
  engaged_by: string | null;
}

/** Backend killswitch'ni o'rab qaytaradi — shu yerda ochamiz. */
interface KillswitchEnvelope {
  killswitch: KillswitchDto;
}

export interface HealthDto {
  status: string;
}

/** GET /agents javobi (backend `AgentResponse` bilan AYNAN mos). */
export interface AgentDto {
  name: string;
  description: string;
  division: string;
  role: string;
  status: string;
  permission_level: string;
  tool_allowlist: string[];
  total_runs: number;
  successful_runs: number;
  failed_runs: number;
  success_rate: number;
  total_tool_calls: number;
}

/** POST /agents/{name}/run javobi (backend `AgentRunResponse`ga mos). */
export interface AgentRunResultDto {
  agent_name: string;
  success: boolean;
  output: string;
  sources: string[];
  tool_calls_count: number;
  steps_count: number;
  error: string | null;
}

/** GET /automation/stats javobi — bo'lim → o'lchov → son. */
export type AutomationStatsDto = Record<string, Record<string, number>>;

/* ── Ish maydoni (Z46) ─────────────────────────────────────────── */

export type ProjectStatus = "active" | "paused" | "done" | "archived";
export type TaskStatus = "todo" | "in_progress" | "blocked" | "done" | "cancelled";
export type TaskPriority = "low" | "medium" | "high" | "urgent";

export interface ProjectDto {
  id: string;
  name: string;
  description: string;
  status: ProjectStatus;
  color: string;
  due_at: string | null;
  created_at: string;
  task_total: number;
  task_done: number;
  /** 0-100 — vazifalardan HISOBLANGAN, qotirilgan foiz emas. */
  progress: number;
}

export interface TaskDto {
  id: string;
  project_id: string | null;
  title: string;
  description: string;
  status: TaskStatus;
  priority: TaskPriority;
  due_at: string | null;
  done_at: string | null;
  assigned_agent: string;
  created_at: string;
}

export interface EventDto {
  id: string;
  project_id: string | null;
  title: string;
  description: string;
  location: string;
  starts_at: string;
  ends_at: string | null;
  all_day: boolean;
}

/* ── Tizim (Z46.1) ─────────────────────────────────────────────── */

/** O'lchangan ko'rsatkichlar. GPU YO'Q — serverda o'lchanmaydi. */
export interface SystemDto {
  cpu_percent: number;
  memory_percent: number;
  memory_used_mb: number;
  memory_total_mb: number;
  disk_percent: number;
  disk_free_gb: number;
  uptime_seconds: number;
}

export interface IntegrationDto {
  key: string;
  label: string;
  configured: boolean;
  detail: string;
}

/* ── Run (buyruq yuborish) ─────────────────────────────────────── */

export interface ConversationMessageDto {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  created_at: string;
}

export interface NoteSummaryDto {
  title: string;
  size_bytes: number;
  /** Unix soniya — `Date` uchun 1000 ga ko'paytiriladi. */
  modified_at: number;
}

export interface RunDto {
  run_id: string;
  trace_id: string;
  status: string;
  message: string;
  steps_done: number;
  steps_total: number;
  cost_usd: number;
  pending_approval_id: string | null;
}

/** GET /runs javobi — run tarixi (DB'dagi `Run` modeliga mos). */
export interface RunHistoryDto {
  run_id: string;
  status: string;
  command_text: string;
  result_summary: string | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  steps_done: number;
  steps_total: number;
  cost_usd: number;
  tools_used: string[];
}

/* ── TIZIM retseptlari (Z48) ───────────────────────────────────── */

export type RecipeStatus = "ready" | "missing_capability";

export interface RecipeStepDto {
  /** Backend qadam raqamini SATR sifatida yuboradi (`dict[str, str]`). */
  order: string;
  title: string;
  agent_name: string;
}

export interface RecipeDto {
  code: string;
  name: string;
  /** Ega uchun bir qatorlik va'da. */
  promise: string;
  trigger_kind: "time" | "event";
  /** Cron ifodasi (time) yoki hodisa turi (event). */
  trigger_spec: string;
  /** Qo'shimcha ishga tushish vaqtlari — T06 kuniga ikki marta ishlaydi. */
  also_at: string[];
  result: string;
  steps: RecipeStepDto[];
  status: RecipeStatus;
  /** Yetishmayotgan imkoniyatlar — bo'sh bo'lsa retsept tayyor. */
  missing: string[];
  blocked_steps: number[];
}

export interface RecipeInstallDto {
  code: string;
  installed_id: string;
  kind: "time" | "event";
}

export interface ScheduleRuleDto {
  id: string;
  name: string;
  agent_name: string;
  cron_expr: string;
  enabled: boolean;
  run_count: number;
  last_run_at: string | null;
}

/* ── Kamera (Z48.3) ────────────────────────────────────────────── */

export interface CameraInfoDto {
  configured: boolean;
  camera_id: string;
  label: string;
  /** Sozlanmagan bo'lsa — NIMA qilish kerakligi. */
  detail: string;
}

export interface SnapshotDto {
  camera_id: string;
  image_b64: string;
  media_type: string;
  width: number;
  height: number;
  timestamp: string;
  /** `hikvision` yoki `stub` — manba ochiq ko'rsatiladi. */
  source: string;
}

/* ── Jonli manbalar (Z50) ──────────────────────────────────────── */

/** Har bir manba ALOHIDA muvaffaqiyat/xato qaytaradi.
 *
 * Beshta manbadan bittasi o'chsa qolgani baribir ko'rinadi — shu
 * sabab `ok` bloklar darajasida, so'rov darajasida emas. */
export interface FeedBlock<T> {
  ok: boolean;
  /** Ma'lumot qayerdan keldi — ega manbani ko'rib tursin. */
  source: string;
  data: T | null;
  error: string | null;
}

export interface WeatherDto {
  temperature_c: number;
  humidity_percent: number;
  condition: string;
  high_c: number;
  low_c: number;
  observed_at: string;
  /** Kesh yoshi soniyada — 0 bo'lsa hozirgina olingan. */
  age_s: number;
}

export interface QuoteDto {
  symbol: string;
  name: string;
  currency: string;
  price: number;
  change: number;
  change_percent: number;
  /** Oxirgi ~30 kunlik yopilish narxlari — sparkline uchun. */
  spark: number[];
}

export interface HeadlineDto {
  title: string;
  link: string;
  published: string;
}

export interface MatchDto {
  home: string;
  away: string;
  home_score: string;
  away_score: string;
  date: string;
  league: string;
}

export interface RateDto {
  code: string;
  name: string;
  rate: number;
  diff: number;
  date: string;
}

export interface FeedsDto {
  weather: FeedBlock<WeatherDto>;
  stocks: FeedBlock<QuoteDto[]>;
  news: FeedBlock<HeadlineDto[]>;
  sports: FeedBlock<MatchDto[]>;
  rates: FeedBlock<RateDto[]>;
}

/* ── Xotira (Memory) ───────────────────────────────────────────── */

/** Backend `MemoryEntryResponse`ga AYNAN mos. */
export interface MemoryEntryDto {
  id: string | null;
  layer: string;
  content: string;
  summary: string | null;
  tags: string[];
  source: string | null;
  version: number;
  trust_level: string;
  created_at: string | null;
  expires_at: string | null;
}

/** Backend `MemorySearchResultResponse`ga AYNAN mos. */
export interface MemorySearchResultDto {
  entry: MemoryEntryDto;
  similarity: number;
  rank: number;
}

/** POST /memory/ingest-profile javobi (backend `ProfileIngestResponse`ga mos). */
export interface ProfileIngestResultDto {
  sections_found: number;
  added: number;
  failed: number;
  errors: string[];
}

/* ── Chaqiruvlar ───────────────────────────────────────────────── */

export const api = {
  health: () => call<HealthDto>("/health"),

  /** Haqiqiy agentlar — ilgari dashboard'da 5 ta QOTIRILGAN agent turardi. */
  agents: () => call<AgentDto[]>("/agents"),

  agent: {
    /** Bitta agentga vazifa berish — javob HAQIQIY LLM natijasi. */
    run: (name: string, task: string) =>
      call<AgentRunResultDto>(`/agents/${encodeURIComponent(name)}/run`, {
        method: "POST",
        body: JSON.stringify({ task }),
      }),
    /** V-11 lifecycle: activate | pause | disable | archive | ... */
    setStatus: (name: string, action: string, reason = "") =>
      call<AgentDto>(`/agents/${encodeURIComponent(name)}/status`, {
        method: "PATCH",
        body: JSON.stringify({ action, reason }),
      }),
  },

  automationStats: () => call<AutomationStatsDto>("/automation/stats"),

  /** 6 TIZIM retsepti — HALOL holat bilan (tayyor / imkoniyat yetishmaydi). */
  recipes: {
    list: () => call<RecipeDto[]>("/automation/recipes"),
    install: (code: string) =>
      call<RecipeInstallDto>(`/automation/recipes/${code}/install`, { method: "POST" }),
  },

  schedules: () => call<ScheduleRuleDto[]>("/automation/schedules"),

  /** Barcha jonli manbalar bitta so'rovda — NEXUS kartalari uchun. */
  feeds: () => call<FeedsDto>("/feeds"),

  camera: {
    info: () => call<CameraInfoDto>("/camera"),
    /** Sozlanmagan bo'lsa backend 503 qaytaradi — stub rasm YO'Q. */
    snapshot: () => call<SnapshotDto>("/camera/snapshot", { method: "POST" }),
  },

  /** O'lchangan tizim ko'rsatkichlari — soxta CPU/RAM o'rniga. */
  system: () => call<SystemDto>("/system"),

  /** Tekshirilgan integratsiya holati — qo'lda yozilgan flag o'rniga. */
  integrations: () => call<IntegrationDto[]>("/integrations"),

  /** Buyruqni HAQIQATAN backend'ga yuboradi (ilgari canned javob edi). */
  run: (message: string, channel = "web") =>
    call<RunDto>("/run", { method: "POST", body: JSON.stringify({ message, channel }) }),

  /** Run tarixi — DB'dan, o'ylab topilgan ro'yxat o'rniga. */
  runs: {
    list: (limit = 20, offset = 0) =>
      call<RunHistoryDto[]>(`/runs?limit=${limit}&offset=${offset}`),
  },

  /** Obsidian vault eslatmalari — ilgari `/files` bo'sh placeholder edi. */
  notes: (query = "") =>
    call<{ notes: NoteSummaryDto[]; total: number }>(
      `/vault/notes${query ? `?query=${encodeURIComponent(query)}` : ""}`,
    ),

  note: (title: string) =>
    call<{ title: string; content: string }>(`/vault/notes/${encodeURIComponent(title)}`),

  /** Saqlangan suhbat tarixi — ilgari o'ylab topilgan xabarlar edi. */
  messages: (channel = "web", limit = 50) =>
    call<ConversationMessageDto[]>(
      `/conversations/${encodeURIComponent(channel)}/messages?limit=${limit}`,
    ),

  projects: {
    list: () => call<ProjectDto[]>("/projects"),
    create: (body: { name: string; description?: string }) =>
      call<ProjectDto>("/projects", { method: "POST", body: JSON.stringify(body) }),
    update: (id: string, body: Partial<{ name: string; status: ProjectStatus }>) =>
      call<ProjectDto>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    remove: (id: string) => call<void>(`/projects/${id}`, { method: "DELETE" }),
  },

  tasks: {
    list: () => call<TaskDto[]>("/tasks"),
    create: (body: {
      title: string;
      description?: string;
      priority?: TaskPriority;
      project_id?: string | null;
      due_at?: string | null;
    }) => call<TaskDto>("/tasks", { method: "POST", body: JSON.stringify(body) }),
    update: (
      id: string,
      body: Partial<{ title: string; status: TaskStatus; priority: TaskPriority }>,
    ) => call<TaskDto>(`/tasks/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    remove: (id: string) => call<void>(`/tasks/${id}`, { method: "DELETE" }),
  },

  events: {
    list: (range?: { start?: string; end?: string }) => {
      const q = new URLSearchParams();
      if (range?.start) q.set("start", range.start);
      if (range?.end) q.set("end", range.end);
      const suffix = q.toString() ? `?${q.toString()}` : "";
      return call<EventDto[]>(`/events${suffix}`);
    },
    create: (body: { title: string; starts_at: string; location?: string }) =>
      call<EventDto>("/events", { method: "POST", body: JSON.stringify(body) }),
    remove: (id: string) => call<void>(`/events/${id}`, { method: "DELETE" }),
  },

  approvals: {
    /** Bitta run uchun kutilayotgan tasdiqlar. */
    list: (runId: string) =>
      call<ApprovalDto[]>(`/approvals?run_id=${encodeURIComponent(runId)}`),
    /** Global — BARCHA kutilayotgan tasdiqlar (backend `run_id=None` bo'lsa shuni qaytaradi). */
    listAll: () => call<ApprovalDto[]>("/approvals"),
    approve: (id: string, note?: string) =>
      call<ApprovalDecisionDto>(`/approvals/${id}/approve`, {
        method: "POST",
        body: JSON.stringify({ note: note ?? null }),
      }),
    reject: (id: string, note?: string) =>
      call<ApprovalDecisionDto>(`/approvals/${id}/reject`, {
        method: "POST",
        body: JSON.stringify({ note: note ?? null }),
      }),
  },

  memory: {
    /** Semantik qidiruv — `min_similarity` past bo'lsa ko'proq (kamroq aniq) natija. */
    search: (text: string, opts?: { limit?: number; minSimilarity?: number }) =>
      call<MemorySearchResultDto[]>("/memory/search", {
        method: "POST",
        body: JSON.stringify({
          text,
          limit: opts?.limit ?? 10,
          min_similarity: opts?.minSimilarity ?? 0.3,
        }),
      }),
    /** Bitta qatlamdagi yozuvlar (short_term/conversation/task/project/business/personal/knowledge). */
    byLayer: (layer: string, limit = 50) =>
      call<MemoryEntryDto[]>(`/memory/layer/${encodeURIComponent(layer)}?limit=${limit}`),
    /** Profil faylini (markdown) yuklab, bo'limlarga bo'lib PERSONAL qatlamga yozadi.
     *
     * `call()` FormData bilan chaqiriladi — Content-Type qo'lda qo'yilmaydi,
     * brauzer o'zi "multipart/form-data; boundary=…" qo'shadi. */
    ingestProfile: (file: File): Promise<Result<ProfileIngestResultDto>> => {
      const formData = new FormData();
      formData.append("file", file);
      return call<ProfileIngestResultDto>("/memory/ingest-profile", {
        method: "POST",
        body: formData,
      });
    },
  },

  killswitch: {
    status: async (): Promise<Result<KillswitchDto>> => {
      const res = await call<KillswitchEnvelope>("/killswitch");
      return res.ok ? { ok: true, data: res.data.killswitch } : res;
    },
    engage: async (reason = "Dashboard orqali"): Promise<Result<KillswitchDto>> => {
      const res = await call<{ status: string; killswitch: KillswitchDto }>(
        "/killswitch/engage",
        { method: "POST", body: JSON.stringify({ reason }) },
      );
      return res.ok ? { ok: true, data: res.data.killswitch } : res;
    },
    disengage: async (): Promise<Result<KillswitchDto>> => {
      const res = await call<{ status: string; killswitch: KillswitchDto }>(
        "/killswitch/disengage",
        { method: "POST" },
      );
      return res.ok ? { ok: true, data: res.data.killswitch } : res;
    },
  },
};
