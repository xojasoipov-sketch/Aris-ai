"use client";

/** Jonli approval'lar paneli — mavjud backend API'ga ulangan (docs/11 §2.4).
 *
 * 5 soniyada bir poll (WebSocket — ochiq savol, docs/11 §6.1); backend
 * o'chiq bo'lsa jimgina yashirinadi, UI yiqilmaydi.
 */

import { AnimatePresence } from "framer-motion";
import { useCallback, useEffect, useState } from "react";

import { ApprovalCard } from "@/components/ui/devices";
import { TechLabel } from "@/components/ui/primitives";
import { api, type ApprovalDto } from "@/lib/api";
import { sound } from "@/lib/sound";

export function LiveApprovals() {
  const [approvals, setApprovals] = useState<ApprovalDto[]>([]);
  const [reachable, setReachable] = useState(false);

  const refresh = useCallback(async () => {
    const res = await api.approvals.list();
    if (res.ok) {
      setReachable(true);
      setApprovals(res.data.filter((a) => a.status === "pending"));
    } else {
      setReachable(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), 5000);
    return () => clearInterval(t);
  }, [refresh]);

  if (!reachable || approvals.length === 0) return null;

  return (
    <section className="space-y-3">
      <TechLabel>Tasdiq kutilmoqda — {approvals.length}</TechLabel>
      <div className="grid gap-4 md:grid-cols-2">
        <AnimatePresence>
          {approvals.map((a) => (
            <ApprovalCard
              key={a.id}
              approval={{
                id: a.id,
                toolName: a.tool_name ?? "noma'lum tool",
                reason: a.reason,
                preview: a.preview,
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
