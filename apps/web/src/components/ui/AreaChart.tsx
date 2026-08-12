"use client";

/** Area chart — custom SVG (CLAUDE.md: grid chiziqlar juda xira hairline,
 * --accent-blue chiziq, ostida glow gradient). Recharts'siz — yengil.
 */

export function AreaChart({
  data,
  labels,
  width = 560,
  height = 180,
  id = "area",
}: {
  data: number[];
  labels?: string[];
  width?: number;
  height?: number;
  id?: string;
}) {
  if (data.length < 2) return null;
  const max = Math.max(...data) * 1.15;
  const min = 0;
  const pad = { t: 10, r: 8, b: labels ? 22 : 8, l: 8 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;

  const pt = (v: number, i: number): [number, number] => [
    pad.l + (i / (data.length - 1)) * w,
    pad.t + h - ((v - min) / (max - min)) * h,
  ];

  // Silliq egri (Catmull-Rom → bezier taxmini)
  const pts = data.map(pt);
  let d = `M ${pts[0][0]} ${pts[0][1]}`;
  for (let i = 1; i < pts.length; i++) {
    const [x0, y0] = pts[i - 1];
    const [x1, y1] = pts[i];
    const mx = (x0 + x1) / 2;
    d += ` C ${mx} ${y0}, ${mx} ${y1}, ${x1} ${y1}`;
  }

  const gridLines = 4;

  return (
    <svg width={width} height={height} className="max-w-full overflow-visible">
      <defs>
        <linearGradient id={`${id}-fill`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent-blue)" stopOpacity="0.28" />
          <stop offset="100%" stopColor="var(--accent-blue)" stopOpacity="0" />
        </linearGradient>
        <filter id={`${id}-glow`} x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="4" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* Juda xira gorizontal grid */}
      {Array.from({ length: gridLines }, (_, i) => {
        const y = pad.t + (h / gridLines) * (i + 1);
        return (
          <line
            key={i}
            x1={pad.l}
            x2={pad.l + w}
            y1={y}
            y2={y}
            stroke="var(--border-hairline)"
            strokeWidth="1"
          />
        );
      })}

      <path d={`${d} L ${pts[pts.length - 1][0]} ${pad.t + h} L ${pts[0][0]} ${pad.t + h} Z`} fill={`url(#${id}-fill)`} />
      <path d={d} fill="none" stroke="var(--accent-blue)" strokeWidth="2" filter={`url(#${id}-glow)`} />

      {/* Oxirgi nuqta ta'kidlangan */}
      <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="3.5" fill="var(--accent-glow)" />

      {labels
        ? labels.map((l, i) => {
            const x = pad.l + (i / (labels.length - 1)) * w;
            return (
              <text
                key={i}
                x={x}
                y={height - 6}
                textAnchor="middle"
                className="fill-[var(--text-muted)] text-[9px]"
                style={{ fontFamily: "var(--font-geist-mono)" }}
              >
                {l}
              </text>
            );
          })
        : null}
    </svg>
  );
}
