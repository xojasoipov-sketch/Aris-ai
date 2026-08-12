/** ZET backend client — /api/zet/* proksi orqali (next.config.ts rewrite).
 *
 * Muhim qoidalar (docs/PROMPT-FRONTEND-BUILD.md §2):
 *   - Backend'ga YANGI endpoint qo'shilmaydi — faqat mavjudlar
 *   - Backend o'chiq bo'lsa UI yiqilmaydi — har chaqiruv Result qaytaradi
 *
 * Mavjud endpoint'lar (apps/core/src/zet/api/routes/):
 *   GET  /approvals · POST /approvals/{id}/approve · POST /approvals/{id}/reject
 *   POST /killswitch/engage · POST /killswitch/disengage · GET /killswitch
 *   GET  /health
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

/* ── Tiplar (backend Pydantic sxemalariga mos) ─────────────────── */

export interface ApprovalDto {
  id: string;
  run_id: string;
  tool_name: string | null;
  reason: string;
  requested_permission: string;
  preview: Record<string, unknown>;
  status: string;
  created_at: string;
  expires_at: string;
}

export interface KillswitchDto {
  engaged: boolean;
  reason?: string | null;
}

export interface HealthDto {
  status: string;
}

/* ── Chaqiruvlar ───────────────────────────────────────────────── */

export const api = {
  health: () => call<HealthDto>("/health"),
  approvals: {
    list: () => call<ApprovalDto[]>("/approvals"),
    approve: (id: string) => call<unknown>(`/approvals/${id}/approve`, { method: "POST" }),
    reject: (id: string) => call<unknown>(`/approvals/${id}/reject`, { method: "POST" }),
  },
  killswitch: {
    status: () => call<KillswitchDto>("/killswitch"),
    engage: () => call<unknown>("/killswitch/engage", { method: "POST" }),
    disengage: () => call<unknown>("/killswitch/disengage", { method: "POST" }),
  },
};
