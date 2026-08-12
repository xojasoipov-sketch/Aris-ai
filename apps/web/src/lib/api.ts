/** ZET backend client — /api/zet/* proksi orqali (route handler).
 *
 * Muhim qoidalar:
 *   - Backend o'chiq bo'lsa UI yiqilmaydi — har chaqiruv Result qaytaradi
 *   - Soxta ma'lumot YO'Q: sahifa faqat backend bergan narsani ko'rsatadi
 *
 * Tiplar REAL kontraktga mos (jonli backend'da tekshirilgan):
 *   GET  /approvals?run_id=…            → ApprovalDto[]  (run_id MAJBURIY)
 *   POST /approvals/{id}/approve|reject → body {note?} MAJBURIY (bo'sh {} ham bo'ladi)
 *   GET  /killswitch                    → {killswitch: {...}} (ichma-ich — unwrap qilamiz)
 *   POST /killswitch/engage             → body {reason} MAJBURIY
 *   GET  /health                        → {status}
 *   GET  /system                        → o'lchangan CPU/RAM/disk (Z46.1)
 *   GET  /integrations                  → tekshirilgan xizmat holati (Z46.1)
 *   CRUD /projects /tasks /events       → ish maydoni (Z46)
 */

export type Result<T> = { ok: true; data: T } | { ok: false; error: string };

async function call<T>(path: string, init?: RequestInit): Promise<Result<T>> {
  try {
    const res = await fetch(`/api/zet${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
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

/* ── Chaqiruvlar ───────────────────────────────────────────────── */

export const api = {
  health: () => call<HealthDto>("/health"),

  /** Haqiqiy agentlar — ilgari dashboard'da 5 ta QOTIRILGAN agent turardi. */
  agents: () => call<AgentDto[]>("/agents"),

  automationStats: () => call<AutomationStatsDto>("/automation/stats"),

  /** O'lchangan tizim ko'rsatkichlari — soxta CPU/RAM o'rniga. */
  system: () => call<SystemDto>("/system"),

  /** Tekshirilgan integratsiya holati — qo'lda yozilgan flag o'rniga. */
  integrations: () => call<IntegrationDto[]>("/integrations"),

  /** Buyruqni HAQIQATAN backend'ga yuboradi (ilgari canned javob edi). */
  run: (message: string) =>
    call<RunDto>("/run", { method: "POST", body: JSON.stringify({ message }) }),

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
    /** run_id MAJBURIY — global "hammasi" endpoint'i backend'da yo'q. */
    list: (runId: string) =>
      call<ApprovalDto[]>(`/approvals?run_id=${encodeURIComponent(runId)}`),
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
