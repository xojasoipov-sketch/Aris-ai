"use client";

/** Floating assistant widget — FAZA 5 speci.
 *
 * Pastki-o'ng burchakda 56px mini-orb; bosilganda kvadrat menyu ochiladi
 * (AnimatePresence, scale+opacity, spring). Menyu: Gaplashish, Eslatma
 * yaratish, Topshiriq berish, Fayl izlash, Agent chaqirish, Kamera ochish.
 *
 * Bildirishnoma namoyishi: sessiyada bir marta, 12s dan keyin CEO Agent
 * xabari keladi (notification tovushi bilan) — real RunEvent push keyin
 * shu kanalga ulanadi.
 */

import {
  Bell,
  Bot,
  Camera,
  FileSearch,
  ListPlus,
  MessageCircle,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { NeuroOrb } from "@/components/core/NeuroOrb";
import {
  NotificationCard,
  type NotificationData,
} from "@/components/widget/NotificationCard";
import { sound } from "@/lib/sound";

const MENU = [
  { icon: MessageCircle, label: "Gaplashish", href: "/ai-chat" },
  { icon: Bell, label: "Eslatma yaratish", href: "/tasks" },
  { icon: ListPlus, label: "Topshiriq berish", href: "/tasks" },
  { icon: FileSearch, label: "Fayl izlash", href: "/files" },
  { icon: Bot, label: "Agent chaqirish", href: "/agents" },
  { icon: Camera, label: "Kamera ochish", href: "/camera" },
] as const;

export function FloatingAssistant() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationData[]>([]);

  /* Demo bildirishnoma — sessiyada bir marta */
  useEffect(() => {
    if (sessionStorage.getItem("zet.demo.notif")) return;
    const t = setTimeout(() => {
      sessionStorage.setItem("zet.demo.notif", "1");
      sound.play("notification");
      setNotifications([
        {
          id: "demo-1",
          agent: "CEO Agent",
          message: "Yangi hisobot tayyor — haftalik strategik tahlil.",
          time: "hozir",
          seed: 1,
        },
      ]);
    }, 12000);
    return () => clearTimeout(t);
  }, []);

  return (
    <div className="fixed bottom-14 right-5 z-50 flex flex-col items-end gap-3 lg:bottom-12">
      {/* Bildirishnomalar to'plami */}
      <AnimatePresence>
        {notifications.map((n) => (
          <NotificationCard
            key={n.id}
            data={n}
            onClose={(id) => setNotifications((cur) => cur.filter((x) => x.id !== id))}
          />
        ))}
      </AnimatePresence>

      {/* Kvadrat menyu */}
      <AnimatePresence>
        {open ? (
          <motion.div
            initial={{ opacity: 0, scale: 0.9, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9, y: 8 }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
            className="floating grid w-64 grid-cols-2 gap-1.5 p-2"
          >
            {MENU.map(({ icon: I, label, href }) => (
              <button
                key={label}
                onClick={() => {
                  sound.play("tick");
                  setOpen(false);
                  router.push(href);
                }}
                className="flex flex-col items-center gap-1.5 rounded-[10px] px-2 py-3 text-center text-[11px] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text-primary)]"
              >
                <I size={18} strokeWidth={1.5} className="text-[var(--accent-blue)]" />
                {label}
              </button>
            ))}
          </motion.div>
        ) : null}
      </AnimatePresence>

      {/* Orb tugma */}
      <motion.button
        aria-label={open ? "Menyuni yopish" : "Tezkor menyu"}
        whileTap={{ scale: 0.94 }}
        transition={{ type: "spring", stiffness: 300, damping: 30 }}
        onClick={() => {
          sound.play(open ? "tick" : "wake");
          setOpen((v) => !v);
        }}
        className="relative h-14 w-14 rounded-full border border-[var(--border-hairline)] bg-[var(--bg-elevated)] outline-none transition-colors hover:border-[var(--border-active)]"
      >
        <NeuroOrb state={open ? "listening" : "idle"} mini seedOffset={13} className="absolute inset-0.5" />
      </motion.button>
    </div>
  );
}
