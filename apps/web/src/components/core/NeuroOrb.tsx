"use client";

/** <NeuroOrb /> — ZET'ning signature 3D komponenti (CLAUDE.md master tizim).
 *
 * Haqiqiy 3D nuqta-bulut (screenspace 2D EMAS): R3F + custom GLSL.
 * Bitta shader — barcha holatlar uniform'lar bilan boshqariladi:
 *
 *   idle       silliq aylanish (~26s/aylanish), Fibonacci sfera
 *   listening  mikrofon amplitudasiga to'lqin deformatsiyasi (uLevel)
 *   thinking   ichki pulsatsiya + noise displacement + zichlashish
 *   speaking   sfera → profil-yuz morph (CPU'da hisoblangan target, uMorph)
 *   searching  nuqtalar radial tarqalib qaytadi (per-particle fazali loop)
 *   offline    aylanish to'xtaydi, nurlanish 40% ga xira
 *
 * Mini rejim (chip ikonkalari): particles≈700, bitta shader — 5 xil alohida
 * animatsiya yozilmaydi, seed/parametr farqlaydi.
 *
 * Harakat og'ir va "fizik": barcha parametrlar lerp bilan silliq o'tadi,
 * bounce YO'Q. prefers-reduced-motion'da vaqt 10x sekinlashadi.
 */

import { Canvas, useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";

export type OrbState =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "searching"
  | "offline";

/* Holat → maqsad parametrlar (har kadr lerp qilinadi) */
const PARAMS: Record<
  OrbState,
  {
    speed: number; // aylanish rad/s
    noise: number; // sirt shovqini
    bright: number; // umumiy yorqinlik
    morph: number; // 0=sfera, 1=yuz
    scatter: number; // searching tarqalish
    squeeze: number; // thinking zichlashish (radius masshtabi)
    wave: number; // listening to'lqin kuchi
  }
> = {
  idle: { speed: 0.24, noise: 0.05, bright: 0.85, morph: 0, scatter: 0, squeeze: 1, wave: 0 },
  listening: { speed: 0.16, noise: 0.05, bright: 0.95, morph: 0, scatter: 0, squeeze: 1, wave: 0.55 },
  thinking: { speed: 0.55, noise: 0.17, bright: 1.15, morph: 0, scatter: 0, squeeze: 0.92, wave: 0 },
  speaking: { speed: 0, noise: 0.045, bright: 1.0, morph: 1, scatter: 0, squeeze: 1, wave: 0.35 },
  searching: { speed: 0.3, noise: 0.06, bright: 1.0, morph: 0, scatter: 1, squeeze: 1, wave: 0 },
  offline: { speed: 0, noise: 0.02, bright: 0.4, morph: 0, scatter: 0, squeeze: 1, wave: 0 },
};

/* ── Profil-yuz nuqta buluti (speaking morph target) ───────────────
 * Bosh: orqa qismi ellipsoid "kalla", old qismi (−X tomonga qaragan
 * ponada) profil egri chizig'i — peshona/burun/lab/iyak/bo'yin.
 * Mockup'dagi yuz chapga qaragan — kamera +Z'da, burun −X'da.
 */
const FACE_PROFILE: [number, number][] = [
  // [y, radius] — Y o'qidan gorizontal masofa
  [1.0, 0.06],
  [0.85, 0.44],
  [0.6, 0.66],
  [0.35, 0.73], // peshona
  [0.22, 0.69], // qosh osti
  [0.12, 0.71], // burun ko'prigi
  [0.02, 0.86], // burun uchi
  [-0.04, 0.65], // burun osti
  [-0.11, 0.69], // ustki lab
  [-0.17, 0.63], // og'iz
  [-0.25, 0.67], // pastki lab
  [-0.35, 0.6], // iyak
  [-0.5, 0.42], // jag' → bo'yin
  [-0.75, 0.35],
  [-1.0, 0.33],
];

function profileRadius(y: number): number {
  const pts = FACE_PROFILE;
  if (y >= pts[0][0]) return pts[0][1];
  for (let i = 0; i < pts.length - 1; i++) {
    const [y0, r0] = pts[i];
    const [y1, r1] = pts[i + 1];
    if (y <= y0 && y >= y1) {
      const t = (y0 - y) / (y0 - y1);
      return r0 + (r1 - r0) * t;
    }
  }
  return pts[pts.length - 1][1];
}

function buildGeometry(count: number, seedOffset: number) {
  const pos = new Float32Array(count * 3);
  const target = new Float32Array(count * 3);
  const seed = new Float32Array(count);
  const golden = Math.PI * (3 - Math.sqrt(5));

  for (let i = 0; i < count; i++) {
    // Fibonacci sfera — teng taqsimot
    const y = 1 - (i / (count - 1)) * 2;
    const rH = Math.sqrt(Math.max(0, 1 - y * y));
    const th = golden * (i + seedOffset * 97);
    const x = Math.cos(th) * rH;
    const z = Math.sin(th) * rH;
    pos[i * 3] = x;
    pos[i * 3 + 1] = y;
    pos[i * 3 + 2] = z;
    seed[i] = ((i * 2654435761) % 1000) / 1000;

    // Yuz target: −X tomon ponada profil, qolgani kalla ellipsoidi
    const hLen = Math.sqrt(x * x + z * z) || 1e-6;
    const dx = x / hLen;
    const dz = z / hLen;
    // −X yo'nalishdan burchak masofasi (0 = to'g'ri old, π = orqa)
    const ang = Math.acos(Math.min(1, Math.max(-1, -dx)));
    const faceW = Math.pow(Math.max(0, 1 - ang / 1.15), 1.4);
    const rBack = rH * 0.72;
    const rFace = profileRadius(y);
    const rT = rBack + (rFace - rBack) * faceW;
    target[i * 3] = dx * rT;
    target[i * 3 + 1] = y;
    target[i * 3 + 2] = dz * rT * 0.72; // bosh eni torroq — profil aniq o'qiladi
  }
  return { pos, target, seed };
}

const VERT = /* glsl */ `
uniform float uTime;
uniform float uRot;
uniform float uNoise;
uniform float uMorph;
uniform float uScatter;
uniform float uSqueeze;
uniform float uWave;
uniform float uLevel;
uniform float uDpr;
uniform float uSize;
attribute vec3 aTarget;
attribute float aSeed;
varying float vGlow;

float n3(vec3 p) {
  return sin(p.x * 1.9 + uTime * 0.9) * sin(p.y * 2.4 + uTime * 0.6) * sin(p.z * 2.1 + uTime * 1.1);
}

void main() {
  // Sfera ↔ yuz morph (CPU target bilan)
  vec3 p = mix(position, aTarget, uMorph);

  // Aylanish — Y o'qi, burchak CPU'dan (speaking'da 0 ga easing qilinadi)
  float c = cos(uRot);
  float s = sin(uRot);
  p = vec3(c * p.x - s * p.z, p.y, s * p.x + c * p.z);

  vec3 dir = normalize(p + vec3(1e-5));

  // thinking: zichlashish
  p *= uSqueeze;

  // Sirt shovqini — "tirik" nafas
  float nz = n3(p * 2.2 + aSeed * 7.0);
  p += dir * nz * uNoise;

  // listening: amplitudaga bog'liq gorizontal to'lqin halqalari
  p += dir * sin(p.y * 9.0 - uTime * 5.0) * uWave * uLevel * 0.07;

  // searching: fazali radial tarqalish-qaytish
  float sc = pow(max(0.0, sin(uTime * 1.4 + aSeed * 6.2831)), 3.0);
  p += dir * sc * uScatter * (0.35 + aSeed * 0.45);

  vGlow = 0.5 + nz * 2.0 + sc * uScatter * 2.5;

  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = (0.9 + aSeed * 0.9) * (uSize / -mv.z) * uDpr;
}
`;

const FRAG = /* glsl */ `
uniform float uBright;
varying float vGlow;

void main() {
  vec2 uv = gl_PointCoord - 0.5;
  float d = length(uv);
  float alpha = smoothstep(0.5, 0.1, d);

  // Deyarli mono: oq nuqta + --accent-blue tint, issiq nuqtalarda --accent-glow
  vec3 white = vec3(0.95, 0.96, 0.97);
  vec3 blue  = vec3(0.298, 0.553, 1.0);   /* #4C8DFF */
  vec3 hot   = vec3(0.49, 0.827, 0.988);  /* #7DD3FC */
  vec3 col = mix(mix(white, blue, 0.28), hot, clamp(vGlow - 0.6, 0.0, 1.0) * 0.5);

  gl_FragColor = vec4(col * uBright, alpha * 0.6);
}
`;

function Cloud({
  state,
  particles,
  level,
  seedOffset,
  size,
  dim = 1,
}: {
  state: OrbState;
  particles: number;
  level?: number;
  seedOffset: number;
  size: number;
  /** Mini rejimda yorqinlikni pasaytirish (additive blowout oldini oladi) */
  dim?: number;
}) {
  const mat = useRef<THREE.ShaderMaterial>(null);
  const rot = useRef(0);
  const fakeLevel = useRef(0.5);
  const reduced =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const geo = useMemo(() => buildGeometry(particles, seedOffset), [particles, seedOffset]);

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uRot: { value: 0 },
      uNoise: { value: PARAMS.idle.noise },
      uBright: { value: PARAMS.idle.bright },
      uMorph: { value: 0 },
      uScatter: { value: 0 },
      uSqueeze: { value: 1 },
      uWave: { value: 0 },
      uLevel: { value: 0.5 },
      uDpr: { value: 1 },
      uSize: { value: size },
    }),
    [size],
  );

  useFrame(({ gl }, delta) => {
    if (!mat.current) return;
    const u = mat.current.uniforms;
    const t = PARAMS[state];
    const dt = reduced ? delta * 0.1 : delta;
    u.uTime.value += dt;
    u.uDpr.value = gl.getPixelRatio();

    // Aylanish: speaking'da eng yaqin 2π karraga silliq easing (yuz old tomonga)
    if (state === "speaking") {
      const twoPi = Math.PI * 2;
      const nearest = Math.round(rot.current / twoPi) * twoPi;
      rot.current += (nearest - rot.current) * Math.min(1, delta * 3);
    } else {
      rot.current += t.speed * dt;
    }
    u.uRot.value = rot.current;

    // Mikrofon darajasi: tashqi prop bo'lmasa — silliq soxta nafas
    if (level == null) {
      fakeLevel.current +=
        (0.35 + 0.55 * Math.abs(Math.sin(u.uTime.value * 1.7)) - fakeLevel.current) *
        Math.min(1, delta * 4);
      u.uLevel.value = fakeLevel.current;
    } else {
      u.uLevel.value += (level - u.uLevel.value) * Math.min(1, delta * 8);
    }

    // Silliq holat o'tishlari (~1.2s) — sakrash yo'q
    const k = Math.min(1, delta * 2.8);
    u.uNoise.value += (t.noise - u.uNoise.value) * k;
    u.uBright.value += (t.bright * dim - u.uBright.value) * k;
    u.uMorph.value += (t.morph - u.uMorph.value) * Math.min(1, delta * 2.2);
    u.uScatter.value += (t.scatter - u.uScatter.value) * k;
    u.uSqueeze.value += (t.squeeze - u.uSqueeze.value) * k;
    u.uWave.value += (t.wave - u.uWave.value) * k;
  });

  return (
    <points>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[geo.pos, 3]} />
        <bufferAttribute attach="attributes-aTarget" args={[geo.target, 3]} />
        <bufferAttribute attach="attributes-aSeed" args={[geo.seed, 1]} />
      </bufferGeometry>
      <shaderMaterial
        ref={mat}
        vertexShader={VERT}
        fragmentShader={FRAG}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  );
}

export function NeuroOrb({
  state,
  className,
  mini = false,
  level,
  seedOffset = 0,
}: {
  state: OrbState;
  className?: string;
  /** Chip ikonkasi rejimi — kam zarracha, past DPR */
  mini?: boolean;
  /** Mikrofon amplitudasi 0..1 (listening); berilmasa soxta nafas */
  level?: number;
  /** Mini variantlar bir-biridan farq qilishi uchun */
  seedOffset?: number;
}) {
  return (
    <div className={className} aria-hidden>
      <Canvas
        camera={{ position: [0, 0, 2.55], fov: 50 }}
        gl={{ antialias: false, alpha: true, powerPreference: "high-performance" }}
        dpr={mini ? 1 : [1, 2]}
      >
        <Cloud
          state={state}
          particles={mini ? 450 : 14000}
          level={level}
          seedOffset={seedOffset}
          size={mini ? 4 : 5.5}
          dim={mini ? 0.7 : 1}
        />
      </Canvas>
    </div>
  );
}
