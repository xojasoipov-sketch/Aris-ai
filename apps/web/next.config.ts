import type { NextConfig } from "next";

/** ZET web — Next.js konfiguratsiyasi.
 *
 * `/api/zet/*` proksisi endi `rewrites()` EMAS, balki haqiqiy route
 * handler: `src/app/api/zet/[...path]/route.ts`.
 *
 * Sabab: rewrite so'rovga header qo'sha olmaydi, backend esa
 * `Authorization: Bearer <token>` talab qiladi (Z39.1). Route handler
 * server tomonda ishlagani uchun `ZET_API_TOKEN` brauzerga chiqmaydi.
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,
};

export default nextConfig;
