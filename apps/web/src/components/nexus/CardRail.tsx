"use client";

/** NEXUS karta karuseli — referens rasmning markaziy elementi (Z50).
 *
 * Rasmda o'nta shisha karta gorizontal qatorda turadi, o'rtadagisi
 * (AI) kattaroq va yorug'roq. Chetga borgan sari kartalar kichrayadi
 * va xiralashadi — perspektiva hissi shundan.
 *
 * NEGA CSS TRANSFORM, 3D KUTUBXONA EMAS. Kartalar tekis to'rtburchak
 * va faqat masshtab/opacity/gorizontal siljish bilan joylashadi —
 * bu `translateX + scale` bilan to'liq chiqadi. Uch o'lchovli sahna
 * qo'shish (react-three-fiber) matnni WebGL ichida chizishni talab
 * qilardi: tanlanmaydigan, ekran o'quvchiga ko'rinmaydigan va
 * telefonda sekin. Markaziy sfera esa haqiqatan 3D va u alohida
 * komponentda qoladi.
 *
 * KLAVIATURA MAJBURIY. Qo'l bilan boshqarish qo'shimcha yo'l, asosiy
 * emas: chap/o'ng strelka va Tab ishlaydi, kamera rad etilsa ham
 * karusel to'liq boshqariladi.
 */

import { motion } from "motion/react";
import type { ReactNode } from "react";
import { useCallback, useEffect, useRef } from "react";

import { sound } from "@/lib/sound";

export interface RailCard {
  id: string;
  /** Kartaning yuqoridagi nomi — rasmda BOSH HARFLARDA. */
  title: string;
  /** Nom ostidagi ikki qatorli izoh. */
  subtitle: string;
  /** Asosiy qiymat — yo'q bo'lsa karta "ulanmagan" holatida chiziladi. */
  body: ReactNode;
  /** Pastki chap burchakdagi kichik yorliq. */
  footnote?: string;
  /** Manba javob bermagan bo'lsa — sabab shu yerda. */
  error?: string | null;
}

const GAP_PX = 178;
"Qo'shni kartalar markazlari orasidagi masofa — kartadan tor, ya'ni chetdagilari qisman ustma-ust tushadi (rasmda ham shunday).";

interface Props {
  cards: RailCard[];
  active: number;
  onActiveChange: (index: number) => void;
}

export function CardRail({ cards, active, onActiveChange }: Props) {
  const railRef = useRef<HTMLDivElement>(null);

  const move = useCallback(
    (delta: number) => {
      const next = Math.min(Math.max(active + delta, 0), cards.length - 1);
      if (next !== active) {
        sound.play("tick");
        onActiveChange(next);
      }
    },
    [active, cards.length, onActiveChange],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        move(-1);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        move(1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [move]);

  return (
    <div
      ref={railRef}
      role="listbox"
      aria-label="NEXUS kartalari"
      aria-orientation="horizontal"
      tabIndex={0}
      className="relative flex h-[19rem] w-full items-center justify-center outline-none focus-visible:ring-1 focus-visible:ring-[var(--border-active)]"
    >
      {cards.map((card, i) => {
        const offset = i - active;
        const distance = Math.abs(offset);
        // Chetdagi kartalar ko'rinmaydi — DOM'da qoladi (o'qish
        // tartibi buzilmasin), lekin chizilmaydi.
        if (distance > 4) return null;

        const isCenter = offset === 0;
        const scale = isCenter ? 1 : Math.max(0.72, 0.9 - distance * 0.05);
        const opacity = isCenter ? 1 : Math.max(0.28, 0.72 - distance * 0.14);

        return (
          <motion.button
            key={card.id}
            role="option"
            aria-selected={isCenter}
            onClick={() => {
              sound.play("tick");
              onActiveChange(i);
            }}
            initial={false}
            animate={{ x: offset * GAP_PX, scale, opacity, zIndex: 20 - distance }}
            transition={{ type: "spring", stiffness: 260, damping: 30 }}
            className="absolute h-[17.5rem] w-[10.5rem] overflow-hidden rounded-[16px] border p-3.5 text-left backdrop-blur-[2px] transition-colors"
            style={{
              borderColor: isCenter ? "var(--border-active)" : "var(--border-hairline)",
              background: isCenter
                ? "linear-gradient(180deg, rgba(76,141,255,0.10), rgba(11,14,20,0.72))"
                : "rgba(11,14,20,0.58)",
              boxShadow: isCenter ? "0 0 0 1px rgba(76,141,255,0.22)" : "none",
            }}
          >
            <div className="flex h-full flex-col">
              <div className="text-[13px] font-semibold tracking-wide text-[var(--text-primary)]">
                {card.title}
              </div>
              <div className="mt-0.5 text-[10px] leading-tight text-[var(--text-muted)]">
                {card.subtitle}
              </div>

              <div className="mt-3 min-h-0 flex-1 overflow-hidden">
                {card.error ? (
                  <p className="text-[10px] leading-relaxed text-[var(--status-working)]">
                    Manba javob bermadi — {card.error}
                  </p>
                ) : (
                  card.body
                )}
              </div>

              {card.footnote ? (
                <div className="data pt-2 text-[9px] text-[var(--text-muted)]">
                  {card.footnote}
                </div>
              ) : null}
            </div>
          </motion.button>
        );
      })}
    </div>
  );
}
