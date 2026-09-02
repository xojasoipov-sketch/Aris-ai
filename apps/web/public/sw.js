/* ZET service worker — minimal offline-first strategy.
 *
 * Manba: apps/web/CLAUDE.md sifat standarti. Bu SW ambient/dekorativ
 * emas — u ilova qobig'ini offline'da tirik saqlaydi va API'ni
 * network-first oladi. State-changing endpoint'lar (run/killswitch)
 * hech qachon cache'lanmaydi — approval oqimi (V-32) buzilmasin.
 */

const CACHE_VERSION = "zet-v1";
const APP_SHELL_CACHE = `${CACHE_VERSION}-shell`;
const RUNTIME_CACHE = `${CACHE_VERSION}-runtime`;

// Ilova qobig'i — install paytida cache'ga olinadi.
const APP_SHELL = ["/", "/manifest.webmanifest", "/icon-192.svg", "/icon-512.svg"];

// State-changing yoki hech qachon cache'lanmasligi kerak bo'lgan yo'llar.
const NEVER_CACHE_PATHS = ["/api/v1/run", "/api/v1/killswitch"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(APP_SHELL_CACHE)
      .then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
      .catch(() => {
        // Shell prewarm ixtiyoriy — xatolik SW o'rnatilishini to'xtatmaydi.
      }),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => !key.startsWith(CACHE_VERSION))
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

/**
 * Cache-first: static asset uchun (JS/CSS/rasm/font). Tarmoq bo'sh
 * bo'lsa ham darhol javob qaytariladi.
 */
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response && response.ok && response.type === "basic") {
    const cache = await caches.open(RUNTIME_CACHE);
    cache.put(request, response.clone());
  }
  return response;
}

/**
 * Network-first: API/data uchun. Offline bo'lsa, cache'dagi eski
 * javob qaytariladi (agar bor bo'lsa).
 */
async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      const cache = await caches.open(RUNTIME_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    const cached = await caches.match(request);
    if (cached) return cached;
    throw err;
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;

  // Faqat GET so'rovlari cache'lanadi (POST/PUT/DELETE/PATCH — tarmoqqa).
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  // Faqat o'z origin — cross-origin so'rovlarga aralashmaymiz.
  if (url.origin !== self.location.origin) return;

  // State-changing endpoint'lar — hech qachon cache.
  if (NEVER_CACHE_PATHS.some((path) => url.pathname.startsWith(path))) return;

  // Next.js HMR / dev-server so'rovlariga aralashmaymiz.
  if (url.pathname.startsWith("/_next/webpack-hmr")) return;

  // API — network-first (backend proksisi /api/zet/*, kelajakda /api/v1/*).
  const isApi = url.pathname.startsWith("/api/");
  if (isApi) {
    event.respondWith(networkFirst(request));
    return;
  }

  // Navigatsiya (HTML sahifa) — network-first, offline'da shell.
  if (request.mode === "navigate") {
    event.respondWith(
      networkFirst(request).catch(() =>
        caches.match("/").then((r) => r || Response.error()),
      ),
    );
    return;
  }

  // Static asset — cache-first.
  event.respondWith(cacheFirst(request));
});
