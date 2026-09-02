# ADR-0001 — Tech Stack

- **Status:** Qabul qilindi (2026-08-11)
- **Qaror qabul qildi:** Loyiha egasi
- **Bog'liq:** `docs/01-VISION-GAP.md` §2

## Kontekst

ZET — bir egali shaxsiy AI operatsion tizim. Yadro talablari: LLM orkestratsiyasi,
tool-calling, davomli holat mashinasi, ovoz (STT/TTS), kompyuter ko'rishi (kamera,
OCR, obyekt aniqlash), qurilma boshqaruvi. Repository bo'sh — legacy cheklov yo'q.

## Qaror

**Backend yadro: Python 3.12 + FastAPI.** Frontend alohida: Next.js/TypeScript (Bo'lim 10).

| Qatlam | Tanlov |
|---|---|
| Til | Python 3.12 |
| Web framework | FastAPI + Pydantic v2 |
| ORM / migratsiya | SQLAlchemy 2.0 (async) + Alembic |
| DB | PostgreSQL 16 + `pgvector` |
| Cache / queue | Redis 7 |
| Worker | ARQ |
| Paket boshqaruvi | uv |
| Sifat darvozalari | ruff · mypy --strict · pytest · gitleaks |
| LLM | Anthropic Claude (asosiy) + OpenAI (fallback) |
| LLM observability | Langfuse (self-hosted) |
| Deploy | Docker Compose · 1 ta VPS · Caddy |

## Sabab

1. **AI ekotizimi.** Bo'lim 8 (kamera/vision) va Bo'lim 5 (ovoz) uchun `faster-whisper`,
   YOLO, `ffmpeg` bindinglari, OCR — bularning hammasi Python'da birinchi darajali.
   TypeScript'da bu ishlar baribir alohida Python xizmatini talab qilardi.
2. **Async I/O.** FastAPI + SQLAlchemy async + ARQ bir xil `asyncio` modelida ishlaydi;
   ZET yuki deyarli butunlay I/O-bound (LLM API, DB, tashqi servislar).
3. **Bitta DB.** `pgvector` semantik xotirani (Bo'lim 2) alohida vektor bazasisiz beradi —
   bir egali tizim uchun Pinecone/Qdrant ortiqcha operatsion yuk.
4. **Kubernetes emas.** Bitta ega, bitta VPS. Compose yetarli; murakkablik R-08 ga qarshi.

## Rad etilgan variantlar

| Variant | Nega rad etildi |
|---|---|
| To'liq TypeScript (Hono/NestJS) | Vision/audio kutubxonalari zaif; Bo'lim 8 da baribir Python sidecar kerak bo'lardi — ikki til, ikki deploy |
| Go | LLM tooling va AI kutubxonalari yetishmaydi |
| Django | Sinxron ORM, og'ir, API-first emas |
| Celery | Sinxron model, konfiguratsiya og'ir; ARQ yengilroq va async-native |
| Alohida vektor DB | Ortiqcha servis, tranzaksiya chegarasi buziladi |

## Oqibatlar

- ✅ Bo'lim 5/8 dagi eng murakkab integratsiyalar bir tilda qoladi
- ✅ `mypy --strict` boshidan qo'yiladi (Z1.1) — keyin yumshatish qiyin
- ⚠️ Backend va frontend orasida tip almashish avtomatik emas → OpenAI/OpenAPI sxemasidan
  TypeScript tiplarini generatsiya qilish kerak (Bo'lim 10, `openapi-typescript`)
- ⚠️ Python deploy artefakti Node'ga qaraganda og'irroq → ko'p bosqichli Dockerfile
