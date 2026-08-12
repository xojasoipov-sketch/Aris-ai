/** ZET backend client — /api/zet/* proksi orqali (next.config.ts rewrite).
 *
 * Muhim qoidalar (docs/PROMPT-FRONTEND-BUILD.md §2):
 *   - Backend'ga YANGI endpoint qo'shilmaydi — faqat mavjudlar
 *   - Backend o'chiq bo'lsa UI yiqilmaydi — har chaqiruv Result qaytaradi
 *
 * Tiplar REAL kontraktga mos (jonli backend'da tekshirilgan, Z35.1):
 *   GET  /approvals?run_id=…            → ApprovalDto[]  (run_id MAJBURIY)
 *   POST /approvals/{id}/approve|reject → body {note?} MAJBURIY (bo'sh {} ham bo'ladi)
 *   GET  /killswitch                    → {killswitch: {...}} (ichma-ich — unwrap qilamiz)
 *   POST /killswitch/engage             → body {reason} MAJBURIY
 *   GET  /health                        → {status}
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

/* ── Chaqiruvlar ───────────────────────────────────────────────── */

export const api = {
  health: () => call<HealthDto>("/health"),

  /** Haqiqiy agentlar — ilgari dashboard'da 5 ta QOTIRILGAN agent turardi. */
  agents: () => call<AgentDto[]>("/agents"),

  automationStats: () => call<AutomationStatsDto>("/automation/stats"),

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
