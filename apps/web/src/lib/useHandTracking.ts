"use client";

/** Qo'l skeleti bilan boshqaruv — MediaPipe (Z47).
 *
 * Ega talabi: "qo'l bilan boshqarishni qo'sh… qo'l harakatlarini
 * skeletini topib qil, huddi 3D ning ichiga tushib qolganday bo'lsin".
 *
 * MediaPipe HandLandmarker kamera oqimidan 21 ta bo'g'im nuqtasini
 * qaytaradi. Shu nuqtalardan uchta narsa hisoblanadi:
 *
 *   · KURSOR — ko'rsatkich barmoq uchi (8-nuqta) ekran koordinatasida
 *   · CHIMDISH (pinch) — bosh barmoq (4) va ko'rsatkich (8) uchi
 *     yaqinlashsa "bosish"
 *   · OCHIQ KAFT — beshala barmoq yozilgan bo'lsa "to'xtat/qaytar"
 *
 * MASOFA NORMALLASHTIRILADI. Chimdish chegarasi PIKSELDA emas, kaft
 * o'lchamiga NISBATAN o'lchanadi: qo'l kameradan uzoqda bo'lsa barcha
 * masofalar kichrayadi va qat'iy piksel chegarasi ishlamay qolardi.
 *
 * ASSETLAR TASHQI CDN'DAN yuklanadi (WASM + model, ~8 MB). Server
 * internetga chiqa olmasa hook ochiq `error` holatiga o'tadi —
 * jimgina "ishlamayapti" holat qolmasin.
 */

import type { HandLandmarker } from "@mediapipe/tasks-vision";
import { useCallback, useEffect, useRef, useState } from "react";

const WASM_BASE = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.0.1/wasm";
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";

/** Chimdish — kaft kengligiga nisbatan. */
const PINCH_ON = 0.32;
/** Qo'yib yuborish chegarasi kattaroq — chegara atrofida
 * "titrash" (bir-ikki kadrda ochilib-yopilish) bo'lmasligi uchun. */
const PINCH_OFF = 0.45;

export type HandStatus = "idle" | "loading" | "tracking" | "denied" | "error";

export interface HandPoint {
  x: number;
  y: number;
}

export interface HandState {
  status: HandStatus;
  /** Xato sababi — `status === "error"` bo'lganda. */
  error: string;
  /** Ko'rsatkich barmoq uchi (0-1 normallashgan, oyna aks ettirilgan). */
  cursor: HandPoint | null;
  /** Chimdish holati — "bosib turish". */
  pinching: boolean;
  /** Ochiq kaft — "orqaga/bekor qilish" imosi. */
  openPalm: boolean;
  /** 21 ta bo'g'im — skeletni chizish uchun. */
  landmarks: HandPoint[];
  enable: () => Promise<void>;
  videoRef: React.RefObject<HTMLVideoElement | null>;
}

export function useHandTracking(): HandState {
  const [status, setStatus] = useState<HandStatus>("idle");
  const [error, setError] = useState("");
  const [cursor, setCursor] = useState<HandPoint | null>(null);
  const [pinching, setPinching] = useState(false);
  const [openPalm, setOpenPalm] = useState(false);
  const [landmarks, setLandmarks] = useState<HandPoint[]>([]);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const cleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => () => cleanupRef.current?.(), []);

  const enable = useCallback(async () => {
    if (cleanupRef.current) return;
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setStatus("error");
      setError("Bu brauzer kamerani qo'llamaydi");
      return;
    }

    setStatus("loading");

    let landmarker: HandLandmarker;
    try {
      const vision = await import("@mediapipe/tasks-vision");
      const fileset = await vision.FilesetResolver.forVisionTasks(WASM_BASE);
      landmarker = await vision.HandLandmarker.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: MODEL_URL, delegate: "GPU" },
        runningMode: "VIDEO",
        numHands: 1,
      });
    } catch (e) {
      setStatus("error");
      setError(
        e instanceof Error ? `Model yuklanmadi: ${e.message}` : "Qo'l modeli yuklanmadi",
      );
      return;
    }

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
      });
    } catch {
      setStatus("denied");
      landmarker.close();
      return;
    }

    const video = videoRef.current;
    if (!video) {
      stream.getTracks().forEach((t) => t.stop());
      landmarker.close();
      setStatus("error");
      setError("Video elementi tayyor emas");
      return;
    }

    video.srcObject = stream;
    await video.play();

    let raf = 0;
    let lastVideoTime = -1;
    let pinchLatch = false;

    const tick = () => {
      if (video.currentTime !== lastVideoTime && video.readyState >= 2) {
        lastVideoTime = video.currentTime;
        const result = landmarker.detectForVideo(video, performance.now());
        const hand = result.landmarks?.[0];

        if (hand && hand.length >= 21) {
          // Kamera oynadek — foydalanuvchi qo'lini o'ngga
          // surganda kursor ham o'ngga ketishi kerak.
          const points = hand.map((p) => ({ x: 1 - p.x, y: p.y }));
          setLandmarks(points);

          const thumb = points[4];
          const index = points[8];
          const wrist = points[0];
          const middleBase = points[9];

          // Kaft o'lchami — masofa etaloni. Nolga bo'linishdan
          // himoya: qo'l kadrdan chiqib ketayotganda nuqtalar
          // ustma-ust tushishi mumkin.
          const palm =
            Math.hypot(wrist.x - middleBase.x, wrist.y - middleBase.y) || 0.0001;
          const pinchDist = Math.hypot(thumb.x - index.x, thumb.y - index.y) / palm;

          // Gisterezis — chegara atrofida titramaslik uchun.
          if (!pinchLatch && pinchDist < PINCH_ON) pinchLatch = true;
          else if (pinchLatch && pinchDist > PINCH_OFF) pinchLatch = false;

          setPinching(pinchLatch);
          setCursor(index);

          // Ochiq kaft — to'rtala barmoq uchi o'z bo'g'imidan
          // yuqorida (ya'ni yozilgan).
          const extended = [
            points[8].y < points[6].y,
            points[12].y < points[10].y,
            points[16].y < points[14].y,
            points[20].y < points[18].y,
          ].filter(Boolean).length;
          setOpenPalm(extended === 4 && !pinchLatch);
        } else {
          setCursor(null);
          setLandmarks([]);
          setPinching(false);
          setOpenPalm(false);
          pinchLatch = false;
        }
      }
      raf = requestAnimationFrame(tick);
    };

    raf = requestAnimationFrame(tick);
    setStatus("tracking");

    cleanupRef.current = () => {
      cancelAnimationFrame(raf);
      stream.getTracks().forEach((t) => t.stop());
      landmarker.close();
      cleanupRef.current = null;
    };
  }, []);

  return { status, error, cursor, pinching, openPalm, landmarks, enable, videoRef };
}

/** Skelet chiziqlari — MediaPipe qo'l topologiyasi. */
export const HAND_CONNECTIONS: readonly (readonly [number, number])[] = [
  [0, 1], [1, 2], [2, 3], [3, 4],          // bosh barmoq
  [0, 5], [5, 6], [6, 7], [7, 8],          // ko'rsatkich
  [5, 9], [9, 10], [10, 11], [11, 12],     // o'rta
  [9, 13], [13, 14], [14, 15], [15, 16],   // nomsiz
  [13, 17], [17, 18], [18, 19], [19, 20],  // jimjiloq
  [0, 17],                                  // kaft asosi
] as const;
