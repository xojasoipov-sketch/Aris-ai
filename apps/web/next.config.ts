import type { NextConfig } from "next";

/** ZET web — Next.js konfiguratsiyasi.
 *
 * `/api/zet/*` so'rovlari backend'ga (apps/core, FastAPI) proksi qilinadi —
 * brauzerda CORS muammosi bo'lmaydi, token server tomonda qoladi.
 * Backend manzili ZET_API_URL env orqali (default: lokal dev).
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    const api = process.env.ZET_API_URL ?? "http://localhost:8000";
    return [{ source: "/api/zet/:path*", destination: `${api}/api/v1/:path*` }];
  },
};

export default nextConfig;
