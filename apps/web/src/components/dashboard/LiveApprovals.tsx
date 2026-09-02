"use client";

/** Jonli approval'lar paneli — mavjud backend API'ga ulangan (docs/11 §2.4).
 *
 * REAL KONTRAKT (Z35.1'da jonli backend'da tekshirildi): GET /approvals
 * run_id talab qiladi — global ro'yxat endpoint'i YO'Q va biz backend'ga
 * yangi endpoint qo'shmaymiz. Shuning uchun bu panel faqat faol run
 * konteksti bilan ishlaydi (orchestrator integratsiyasi runId beradi);
 * runId yo'q bo'lsa hech narsa ko'rsatmaydi — bu halol holat.
 *
 * 5 soniyada bir poll; backend o'chiq bo'lsa jimgina yashirinadi.
 */

import { AnimatePresence } from "motion/react";
import { useCallback, useEffect, useState } from "react";

import { ApprovalCard } from "@/components/ui/devices";
import { Eyebrow } from "@/components/ui/primitives";
import { api, type ApprovalDto } from "@/lib/api";
import { sound } from "@/lib/sound";

export function LiveApprovals({ runId }: { runId?: string }) {
  const [approvals, setApprovals] = useState<ApprovalDto[]>([]);

  const refresh = useCallback(async () => {
    if (!runId) return;
    const res = await api.approvals.list(runId);
    if (res.ok) {
      setApprovals(res.data.filter((a) => a.status === "pending"));
    }
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    void refresh();
    const t = setInterval(() => void refresh(), 5000);
    return () => clearInterval(t);
  }, [refresh, runId]);

  if (!runId || approvals.length === 0) return null;

  return (
    <section className="space-y-3">
      <Eyebrow>Tasdiq kutilmoqda — {approvals.length}</Eyebrow>
      <div className="grid gap-4 md:grid-cols-2">
        <AnimatePresence>
          {approvals.map((a) => (
            <ApprovalCard
              key={a.id}
              approval={{
                id: a.id,
                toolName: a.tool_name ?? "noma'lum tool",
                reason: a.reason,
                preview: {},
                expiresAt: a.expires_at,
              }}
              onApprove={async (id) => {
                const r = await api.approvals.approve(id);
                sound.play(r.ok ? "success" : "error");
                void refresh();
              }}
              onReject={async (id) => {
                const r = await api.approvals.reject(id);
                sound.play(r.ok ? "tick" : "error");
                void refresh();
              }}
            />
          ))}
        </AnimatePresence>
      </div>
    </section>
  );
}
