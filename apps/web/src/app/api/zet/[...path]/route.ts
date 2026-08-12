/** Backend proksi — token SERVER tomonda qoladi.
 *
 * Ilgari bu `next.config.ts` ichidagi `rewrites()` edi. Rewrite —
 * shunchaki URL almashtirish: brauzer so'rovi qanday bo'lsa shundayligicha
 * uzatiladi va unga header QO'SHIB BO'LMAYDI. Backend token talab qila
 * boshlagach (Z39.1) rewrite yetarli emas.
 *
 * Route handler esa server tomonda ishlaydi — `ZET_API_TOKEN` brauzerga
 * hech qachon yuborilmaydi. Shu sabab u `NEXT_PUBLIC_` prefiksisiz:
 * `NEXT_PUBLIC_*` o'zgaruvchilar bundle'ga kirib, hammaga ko'rinadi.
 *
 * Xavfsizlik:
 *   - Faqat backend'ning `/api/v1/*` ostiga yo'naltiradi
 *   - Backend javob headerlari qaytarilmaydi (faqat status + tana) —
 *     ichki `Set-Cookie`/server headerlari sizib chiqmaydi
 */

const API_URL = process.env.ZET_API_URL ?? "http://localhost:8000";
const API_TOKEN = process.env.ZET_API_TOKEN ?? "";

/** Uzatiladigan so'rov headerlari — qolganlari tashlab yuboriladi. */
const FORWARDED_HEADERS = ["content-type", "accept", "x-trace-id"] as const;

type RouteContext = { params: Promise<{ path: string[] }> };

async function proxy(request: Request, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  const search = new URL(request.url).search;
  const target = `${API_URL}/api/v1/${path.join("/")}${search}`;

  const headers = new Headers();
  for (const name of FORWARDED_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (API_TOKEN) headers.set("Authorization", `Bearer ${API_TOKEN}`);

  // GET/HEAD tanaga ega bo'lmaydi — aks holda fetch xato beradi.
  const hasBody = request.method !== "GET" && request.method !== "HEAD";

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.text() : undefined,
      cache: "no-store",
    });

    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
      },
    });
  } catch {
    // Backend o'chiq — UI buni Result.error sifatida ko'rsatadi, yiqilmaydi.
    return Response.json({ detail: "Backend bilan aloqa yo'q" }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;

/** Proksi har doim jonli backend'ga boradi — statik keshlanmaydi. */
export const dynamic = "force-dynamic";
