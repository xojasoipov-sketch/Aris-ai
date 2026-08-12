"use client";

/** Neyro shar — ZET'ning vizual yuragi (docs/10 §2, IMG_1701 moodboard).
 *
 * ~14 000 zarracha GPU'da (custom shader), CPU'da faqat uniform'lar.
 * Holatga bog'liq xatti-harakat (docs/10 §3.2):
 *   sleep      sekin aylanish, siyrak nafas
 *   listening  yorqinroq, halqa puls
 *   thinking   zichlashadi, tezroq girdob, cyan kuchayadi
 *   speaking   amplituda to'lqinlari (ovoz kabi)
 *
 * O'tishlar keskin emas — har kadr uniform'lar maqsad qiymatga lerp qilinadi.
 */

import { Canvas, useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";

import type { AssistantState } from "@/lib/assistant-machine";

/* Holat → shader parametrlari (maqsad qiymatlar) */
const STATE_PARAMS: Record<
  AssistantState,
  { speed: number; noise: number; brightness: number; cyanMix: number; pulse: number }
> = {
  sleep: { speed: 0.12, noise: 0.08, brightness: 0.55, cyanMix: 0.25, pulse: 0.0 },
  listening: { speed: 0.25, noise: 0.12, brightness: 1.0, cyanMix: 0.45, pulse: 0.6 },
  thinking: { speed: 0.85, noise: 0.3, brightness: 1.15, cyanMix: 0.85, pulse: 0.25 },
  speaking: { speed: 0.4, noise: 0.18, brightness: 1.05, cyanMix: 0.5, pulse: 1.0 },
  minimized: { speed: 0.1, noise: 0.06, brightness: 0.45, cyanMix: 0.3, pulse: 0.0 },
  notification: { speed: 0.3, noise: 0.15, brightness: 0.9, cyanMix: 0.6, pulse: 0.8 },
};

const VERT = /* glsl */ `
uniform float uTime;
uniform float uSpeed;
uniform float uNoise;
uniform float uPulse;
attribute float aSeed;
varying float vGlow;

// Arzon 3D shovqin (trig asosida — zarrachalar uchun yetarli)
float n3(vec3 p) {
  return sin(p.x * 1.7 + uTime) * sin(p.y * 2.3 + uTime * 0.7) * sin(p.z * 1.9 + uTime * 1.3);
}

void main() {
  vec3 p = position;

  // Sekin girdob — Y o'qi atrofida, tezlik holatga bog'liq
  float ang = uTime * uSpeed + aSeed * 6.2831;
  float c = cos(ang * 0.15);
  float s = sin(ang * 0.15);
  p = vec3(c * p.x - s * p.z, p.y, s * p.x + c * p.z);

  // Radial shovqin — sirt "tirik" nafas oladi
  float noiseAmp = n3(p * 2.0 + aSeed) * uNoise;
  // Puls — ekvatordan qutbga to'lqin (speaking holatida kuchli)
  float wave = sin(p.y * 6.0 - uTime * 3.0) * uPulse * 0.06;
  p *= 1.0 + noiseAmp + wave;

  vGlow = 0.5 + 0.5 * noiseAmp * 6.0;

  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;
  // Masofaga qarab nuqta o'lchami; seed bilan ozgina xilma-xillik
  gl_PointSize = (1.6 + aSeed * 1.2) * (140.0 / -mv.z);
}
`;

const FRAG = /* glsl */ `
uniform float uBrightness;
uniform float uCyanMix;
varying float vGlow;

void main() {
  // Yumshoq dumaloq sprite
  vec2 uv = gl_PointCoord - 0.5;
  float d = length(uv);
  float alpha = smoothstep(0.5, 0.08, d);

  // Oq → cyan gradient (ADR-0005: --text-primary → --accent-cyan)
  vec3 white = vec3(0.91, 0.93, 0.96);
  vec3 cyan  = vec3(0.22, 0.74, 0.97);
  vec3 col = mix(white, cyan, uCyanMix * vGlow);

  gl_FragColor = vec4(col * uBrightness, alpha * 0.85);
}
`;

function Sphere({ state }: { state: AssistantState }) {
  const mat = useRef<THREE.ShaderMaterial>(null);
  const reduced =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const { positions, seeds } = useMemo(() => {
    const N = 14000;
    const pos = new Float32Array(N * 3);
    const seed = new Float32Array(N);
    // Fibonachchi sferasi — tekis taqsimot
    const phi = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < N; i++) {
      const y = 1 - (i / (N - 1)) * 2;
      const r = Math.sqrt(1 - y * y);
      const th = phi * i;
      pos[i * 3] = Math.cos(th) * r;
      pos[i * 3 + 1] = y;
      pos[i * 3 + 2] = Math.sin(th) * r;
      seed[i] = Math.random();
    }
    return { positions: pos, seeds: seed };
  }, []);

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uSpeed: { value: STATE_PARAMS.sleep.speed },
      uNoise: { value: STATE_PARAMS.sleep.noise },
      uBrightness: { value: STATE_PARAMS.sleep.brightness },
      uCyanMix: { value: STATE_PARAMS.sleep.cyanMix },
      uPulse: { value: STATE_PARAMS.sleep.pulse },
    }),
    [],
  );

  useFrame((_, delta) => {
    if (!mat.current) return;
    const u = mat.current.uniforms;
    const target = STATE_PARAMS[state];
    const dt = reduced ? delta * 0.15 : delta;
    u.uTime.value += dt;
    // Silliq o'tish — lerp (~1.5s to'liq o'tish)
    const k = Math.min(1, delta * 2.5);
    u.uSpeed.value += (target.speed - u.uSpeed.value) * k;
    u.uNoise.value += (target.noise - u.uNoise.value) * k;
    u.uBrightness.value += (target.brightness - u.uBrightness.value) * k;
    u.uCyanMix.value += (target.cyanMix - u.uCyanMix.value) * k;
    u.uPulse.value += (target.pulse - u.uPulse.value) * k;
  });

  return (
    <points>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        <bufferAttribute attach="attributes-aSeed" args={[seeds, 1]} />
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

export function ParticleCore({
  state,
  className,
}: {
  state: AssistantState;
  className?: string;
}) {
  return (
    <div className={className} aria-hidden>
      <Canvas
        camera={{ position: [0, 0, 2.6], fov: 50 }}
        gl={{ antialias: false, alpha: true, powerPreference: "high-performance" }}
        dpr={[1, 2]}
      >
        <Sphere state={state} />
      </Canvas>
    </div>
  );
}
