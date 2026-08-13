"use client";

/** Sparkline — birja kartasidagi narx chizig'i (Z50).
 *
 * Referens rasmda STOCKS kartasida yashil o'suvchi chiziq bor. Bu
 * yerdagi chiziq HAQIQIY yopilish narxlaridan chiziladi (Yahoo
 * Finance, oxirgi ~30 kun) — bezak emas.
 *
 * Rang narx yo'nalishidan kelib chiqadi, ya'ni semantik: o'sish
 * yashil, tushish qizil. Bu ZET aksentidan (ko'k) alohida — dizayn
 * tizimi semantik rangni aksent bilan aralashtirmaslikni talab
 * qiladi.
 */

interface Props {
  values: number[];
  /** Ijobiy o'zgarish — yashil, salbiy — qizil. */
  positive: boolean;
  className?: string;
}

const W = 100;
const H = 28;

export function Sparkline({ values, positive, className = "" }: Props) {
  // Ikkitadan kam nuqta chiziq emas — hech narsa chizilmaydi.
  if (values.length < 2) return null;

  const min = Math.min(...values);
  const max = Math.max(...values);
  // Butunlay tekis chiziqda (max === min) nolga bo'linish bo'lardi;
  // bunday holatda chiziq o'rtadan o'tadi.
  const span = max - min || 1;

  const points = values.map((v, i) => {
    const x = (i / (values.length - 1)) * W;
    const y = H - ((v - min) / span) * H;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });

  const stroke = positive ? "var(--status-online)" : "var(--status-alert)";
  const [lastX, lastY] = points[points.length - 1].split(",");

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className={`h-7 w-full ${className}`}
      aria-hidden
    >
      <polyline
        points={points.join(" ")}
        fill="none"
        stroke={stroke}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
      {/* Oxirgi nuqta ta'kidlanadi — ko'z eng yangi qiymatni topsin */}
      <circle cx={lastX} cy={lastY} r="1.8" fill={stroke} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
