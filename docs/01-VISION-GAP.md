# ZET — Vision vs Hozirgi Holat · Gap Analiz va Texnologiya Qarorlari

> Manba: `00-AUDIT.md` · Bosqich: P0 natijasi

---

## 1. Gap matritsasi

Repository bo'sh bo'lgani uchun **barcha vision talablari bajarilmagan**.
Quyidagi jadval "nima bajarilmagan"dan ko'ra **"qaysi tartibda va qanday murakkablikda"**
qurish kerakligini ko'rsatadi — asosiy qiymat shunda.

| # | Vision bloki | Bajarilgan | Murakkablik | Qaysi bo'lim | Tashqi bog'liqlik |
|---|---|---|---|---|---|
| V-04 | Z Core pipeline (intent→plan→route→exec→verify) | 0% | ★★★★☆ | **Bo'lim 1** | LLM API |
| V-31/32 | Ruxsat modeli + approval gate | 0% | ★★★☆☆ | **Bo'lim 1** | — |
| V-34 | Observability / trace / cost | 0% | ★★★☆☆ | **Bo'lim 1** | Langfuse |
| V-29/30 | Model Router | 0% | ★★★☆☆ | **Bo'lim 1** (v1) | 2+ provayder |
| V-13..16 | 7 qatlamli xotira + Obsidian | 0% | ★★★★☆ | Bo'lim 2 | pgvector, Obsidian vault |
| V-12 | Tool Registry | 0% | ★★★☆☆ | Bo'lim 3 | — |
| V-07/09/11 | Agent Runtime + lifecycle | 0% | ★★★★☆ | Bo'lim 3 | — |
| V-10 | Agent Factory | 0% | ★★★★★ | Bo'lim 4 | — |
| V-17/18 | Telegram + Voice | 0% | ★★★☆☆ | Bo'lim 5 | Bot API, STT/TTS |
| V-07 (business) | SMM/Sales/Finance/Support agentlar | 0% | ★★★★☆ | Bo'lim 6 | Platform API'lari |
| V-07 (dev) | Developer Agent + GitHub | 0% | ★★★☆☆ | Bo'lim 7 | GitHub App |
| V-21/22 | Internet Agent + untrusted input | 0% | ★★★★★ | Bo'lim 7 | Search API, browser |
| V-19/20 | Telefon / Kompyuter boshqaruvi | 0% | ★★★★★ | Bo'lim 8 | Companion app |
| V-23/24 | Camera + Vision | 0% | ★★★★☆ | Bo'lim 8 | EZVIZ/RTSP |
| V-25..28 | Automation Engine + Business Factory | 0% | ★★★★★ | Bo'lim 9 | Scheduler/durable exec |
| V-37..41 | Dashboard + Mini App | 0% | ★★★★☆ | Bo'lim 10 | — |
| V-33 | Security hardening | 0% | ★★★★☆ | Bo'lim 11 | — |
| V-35/36 | Kunlik avtonomiya + self-improvement | 0% | ★★★★☆ | Bo'lim 12 | — |

**Qisman bajarilgan:** yo'q. **To'liq bajarilgan:** faqat `P0 — Repository Audit` (ushbu hujjatlar bilan).

---

## 2. Tavsiya etilayotgan tech stack

Har bir tanlov uchun: **nima · nega · muqobili · nega muqobil emas.**

### 2.1. Backend yadro

| Qatlam | Tanlov | Nega | Muqobil (rad etilgan) |
|---|---|---|---|
| Til | **Python 3.12** | LLM/vision/audio ekotizimi eng boy; agent kutubxonalari, YOLO, whisper, ffmpeg bindinglari | Node/TS — AI kutubxonalari zaifroq; Go — LLM tooling yetishmaydi |
| Web framework | **FastAPI + Pydantic v2** | async, OpenAPI avtomatik, tip xavfsizligi, SSE/WebSocket native | Django — og'ir, ORM sinxron; Flask — async zaif |
| ORM | **SQLAlchemy 2.0 (async) + Alembic** | migratsiya, tranzaksiya, tip | Tortoise/Prisma — ekotizim tor |
| DB | **PostgreSQL 16 + `pgvector`** | Bitta bazada relational + vektor. Tranzaksiya, JSONB, LISTEN/NOTIFY | Pinecone/Qdrant — alohida servis, bir egali tizimga ortiqcha |
| Cache/queue | **Redis 7** | queue, rate limit, lock, pub/sub | RabbitMQ — ortiqcha |
| Worker | **ARQ** (async Redis queue) | asyncio native, yengil, FastAPI bilan bir xil model | Celery — sinxron, og'ir konfiguratsiya |

### 2.2. LLM va AI

| Qatlam | Tanlov | Nega |
|---|---|---|
| Asosiy provayder | **Anthropic Claude** | Native tool-use, uzun kontekst, kuchli reasoning |
| Model taqsimoti (Model Router v1) | `simple → Haiku 4.5` · `normal → Sonnet 5` · `complex/planner → Opus 5` · `coding → Sonnet 5/Opus 5` · `vision → Claude vision` | V-29 ni to'g'ridan-to'g'ri qoplaydi |
| Zaxira provayder | **OpenAI** (fallback + embeddings) | Vendor lock-ni kamaytiradi (R-06 xavfi) |
| Embeddings | `text-embedding-3-large` yoki `voyage-3` | pgvector uchun |
| STT | **Whisper (local `faster-whisper`)** yoki Deepgram | Maxfiylik: ovoz lokalda qolishi mumkin |
| TTS | **ElevenLabs** | Sifat; sessiyada MCP konnektori ham mavjud |
| Orkestratsiya | **O'z yozgan Core** (framework emas) | ⬇️ pastda alohida izoh |

> **Muhim qaror — LangChain/CrewAI/AutoGen ISHLATILMAYDI.**
> Sabab: vision `VERIFICATION`, `APPROVAL GATE`, `PERMISSION`, `COST LEDGER` va
> to'liq `TRACE` ni majburiy qiladi. Framework'lar bu bosqichlarni o'z ichida
> yashiradi va ularni to'xtatib/tekshirib bo'lmaydi. Anthropic SDK ning native
> tool-calling'i ustiga ~600 qator o'z orkestratori — aniqroq, sinaladigan va
> debug qilinadigan bo'ladi. `LangGraph` faqat Bo'lim 9 (Automation) da,
> agar durable state machine kerak bo'lsa, qayta ko'rib chiqiladi.

### 2.3. Frontend

| Qatlam | Tanlov | Nega |
|---|---|---|
| Framework | **Next.js 15 (App Router) + React 19 + TypeScript** | SSR, RSC, bitta kod bazasida dashboard + Telegram Mini App |
| Styling | **Tailwind CSS v4 + shadcn/ui** | Mockup'dagi dark glass panel uslubi tez quriladi |
| Animatsiya | **Framer Motion** | Holat o'tishlari (sleep → listening → thinking) |
| 3D/zarrachalar | **react-three-fiber + custom GPU particle shader** | V-41 dagi neyro shar / profil effekti |
| Chartlar | **Recharts** yoki **visx** | Analytics panellari |
| Realtime | **SSE** (stream javob) + **WebSocket** (agent status) | Ikki xil yuk profili |
| Mini App | **@telegram-apps/sdk-react** | V-40 |

### 2.4. Infratuzilma

| Qatlam | Tanlov | Nega |
|---|---|---|
| Konteyner | **Docker + Docker Compose** | Bir egali tizim uchun yetarli |
| Deploy | **1 ta VPS (Hetzner CX32/CCX)** + Caddy (avto-TLS) | ★ **Kubernetes KERAK EMAS** — ortiqcha murakkablik |
| LLM observability | **Langfuse (self-hosted)** | V-34 ni to'g'ridan-to'g'ri qoplaydi: trace, token, cost |
| Infra observability | **Prometheus + Grafana + Loki** | Bo'lim 11 |
| Secret | **SOPS + age** (repo ichida shifrlangan) yoki **Infisical** | V-33 |
| Backup | **restic → S3/B2**, `pg_dump` kunlik | V-33 |
| Media/stream gateway | **go2rtc** (+ ffmpeg) | RTSP/EZVIZ oqimlarini normallashtirish (Bo'lim 8) |
| CI | **GitHub Actions** | lint + type + test + build |

### 2.5. Almashtirishga tavsiya qilinadigan/ehtiyot bo'lish kerak bo'lgan narsalar

| Vision'dagi narsa | Muammo | Tavsiya |
|---|---|---|
| Obsidian = xotira bazasi | Fayl tizimi tranzaksiya, ruxsat va indeks bermaydi | Postgres = **source of truth**, Obsidian = **ko'zga ko'rinadigan proyeksiya** (2 tomonlama sinxron) |
| "Termux" bilan telefon boshqaruvi | Termux Play Store'da yangilanmaydi, ruxsatlar cheklangan, mo'rt | **O'z Android companion app** (Kotlin, foreground service, scoped permissions). Termux — faqat prototip |
| Kompyuterda "to'liq boshqaruv" | Cheksiz kirish = to'liq kompromis yuzasi | **Capability token** modeli: har bir amal uchun scoped, muddatli, bekor qilinadigan ruxsat |
| E-commerce/Finance agentlari | Real pul harakati | Idempotency key + majburiy approval + dry-run rejim |

---

## 3. Arxitekturaviy o'zgarishlar (vision → amaliy dizayn)

Vision to'g'ri, lekin uni **so'zma-so'z** amalga oshirish bir necha joyda ishlamaydi.
Quyida 8 ta majburiy tuzatish.

### 3.1. A-01 · Pipeline emas — davomli holat mashinasi
Slayd 5 chiziqli oqimni ko'rsatadi. Lekin `APPROVAL` (V-32) va `RETRY/RECOVERY` (V-27)
oqimni **to'xtatadi va keyin davom ettiradi** — ba'zan soatlardan keyin.

➡️ `Run` va `Step` **bazada saqlanadigan holat mashinasi** bo'lishi shart:
`PENDING → PLANNING → AWAITING_APPROVAL → EXECUTING → VERIFYING → DONE | FAILED | CANCELLED`.
Xotirada (in-memory) saqlash mumkin emas — protsess qayta ishga tushsa hammasi yo'qoladi.

### 3.2. A-02 · Agent Factory kod generatsiya QILMAYDI
"ZET yangi agent yaratadi" (V-10) — agar bu kod yozib deploy qilish bo'lsa,
tizim o'zini o'zi cheksiz kengaytiradigan va tekshirib bo'lmaydigan bo'lib qoladi.

➡️ Agent = **ma'lumot**, kod emas:
```
agents (id, name, division, role, goal, system_prompt, model_policy,
        tool_allowlist[], permission_level, status, version, created_by)
```
Factory faqat shu yozuvni yaratadi + eval testlarini yuritadi + `DRAFT→TESTING→ACTIVE`
o'tishini so'raydi. Yangi **tool** esa faqat inson tomonidan yoziladi va review'dan o'tadi.

### 3.3. A-03 · Obsidian ikkilamchi
Yuqorida (§2.5). Postgres → Obsidian markdown eksporti + fayl o'zgarishini kuzatuvchi
importer. Konflikt siyosati: `last-write-wins + versiya tarixi` (V-14 "Versioned").

### 3.4. A-04 · Model Router'ga metrika qaytish halqasi kerak
V-30 "success rate" ni o'lchashni talab qiladi. Demak Router faqat statik jadval emas:
har bir `Run` yakunida `(task_class, model, tokens, cost, latency, verified_ok)`
`cost_ledger` ga yoziladi va routing siyosati shu asosda sozlanadi.
**Bu Bo'lim 1 da qo'yilishi shart**, keyin qo'shish qimmatga tushadi.

### 3.5. A-05 · "Untrusted input" arxitekturaviy chegara bo'lishi kerak
V-22 ni faqat prompt bilan bajarib bo'lmaydi. Kerak:
1. Har bir tool natijasi `trust_level` bilan teglanadi (`OWNER` / `SYSTEM` / `UNTRUSTED`).
2. `UNTRUSTED` kontent **hech qachon** planner promptiga to'g'ridan-to'g'ri kirmaydi —
   avval past imtiyozli "reader" model uni **strukturalangan faktlar**ga aylantiradi.
3. `UNTRUSTED` kontekstdan kelib chiqqan hech qanday qadam `WRITE`/`EXECUTE`/`ADMIN`
   darajali toolni **avtomatik** chaqira olmaydi — approval majburiy.

### 3.6. A-06 · Qurilma boshqaruvi = capability token
Har bir qurilma juftlanganda o'z kaliti bo'ladi; har bir amal uchun scope
(`screenshot:read`, `app:launch`, `fs:read:/Users/x/Documents`) va TTL beriladi.
Emergency stop (V-33) barcha tokenlarni bir zumda bekor qiladi.

### 3.7. A-07 · Avtomatlashtirish halqalariga tormoz kerak
`AGENT TRIGGER` (V-26) + `NEXT ACTION` (V-25) → cheksiz sikl xavfi.
➡️ Har bir `Run` da: `depth` limiti, `budget` limiti (USD), `wall-clock` limiti,
bir xil trigger uchun `cooldown` va global `concurrency` chegarasi.

### 3.8. A-08 · 17 agent birdaniga qurilmaydi
➡️ Bosqichli chiqarish:
- Bo'lim 3: **1 ta** generic agent runtime + `Research` agent (eng xavfsiz, read-only)
- Bo'lim 4: Factory + `CEO`, `Operations`
- Bo'lim 6: `SMM`, `Sales`, `Finance`, `Support`
- Bo'lim 7: `Developer`, `QA`
- Bo'lim 12: qolganlari (HR, DevOps, Design, Security, E-commerce, Analytics, Innovation, Prediction)

---

## 4. Xavflar reyestri

| ID | Xavf | Ehtimol | Ta'sir | Yumshatish | Qaysi bo'lim |
|---|---|---|---|---|---|
| R-01 | **Prompt injection** (web, hujjat, kamera OCR, forward qilingan TG xabar) | Yuqori | 🔴 Kritik | A-05 chegarasi, tool allowlist, approval | 1, 7 |
| R-02 | **Xarajat portlashi** (avtonom fon sikllari) | Yuqori | 🔴 Yuqori | Kunlik/oylik budjet limiti, per-run cap, Model Router, alert | 1 |
| R-03 | **Cheksiz avtomatlashtirish sikli** | O'rta | 🔴 Yuqori | A-07 tormozlari | 9 |
| R-04 | **Telegram bot token o'g'irlanishi** = to'liq boshqaruv | O'rta | 🔴 Kritik | Owner ID allowlist, 2-faktor (approval PIN), secret rotation, audit | 5, 11 |
| R-05 | **Qurilma boshqaruvi orqali to'liq kompromis** | O'rta | 🔴 Kritik | A-06 capability token, allow-list buyruqlar, sandbox | 8 |
| R-06 | Vendor lock (bitta LLM provayder) | O'rta | 🟡 O'rta | Provider abstraksiyasi 1-kundan | 1 |
| R-07 | Obsidian sinxron konflikti / ma'lumot yo'qolishi | O'rta | 🟡 O'rta | Postgres source of truth, versiya, backup | 2 |
| R-08 | Vision hajmi vs bitta ishlab chiquvchi resursi | **Yuqori** | 🟡 O'rta | Qat'iy bo'limlar, har bo'limda ishlaydigan mahsulot | hammasi |
| R-09 | Ijtimoiy tarmoq API cheklovlari (SMM avto-publish) | Yuqori | 🟡 O'rta | Faqat rasmiy API; bo'lmasa "draft + qo'lda tasdiq" | 6 |
| R-10 | Kamera oqimi resursni yeyishi (6 kamera 24/7) | O'rta | 🟡 O'rta | go2rtc, event-driven snapshot, doimiy vision analiz emas | 8 |
| R-11 | Sirlar repoga tushib qolishi | O'rta | 🔴 Yuqori | `.gitignore`, gitleaks pre-commit + CI | 1 |
| R-12 | Model API uzilishi | O'rta | 🟡 O'rta | Fallback provayder, retry + circuit breaker | 1 |

---

## 5. Umumiy vaqt bahosi

1 ta to'liq bandlikdagi ishlab chiquvchi (AI yordami bilan) uchun:

| Bo'lim | Fazalar | Baho |
|---|---|---|
| 1 | P0 + P1 | 3–4 hafta |
| 2 | P2 | 2–3 hafta |
| 3 | P3 + P4 | 3–4 hafta |
| 4 | P5 | 2–3 hafta |
| 5 | P6 | 2–3 hafta |
| 6 | P7 | 4–5 hafta |
| 7 | P8 + P9 | 4–5 hafta |
| 8 | P10 + P11 | 5–7 hafta |
| 9 | P12 | 3–4 hafta |
| 10 | P13 | 4–6 hafta |
| 11 | P14 + P15 | 3–4 hafta |
| 12 | P16 + P17 | 3–4 hafta |
| **Jami** | | **≈ 38–52 hafta (9–12 oy)** |

Birinchi **ishlatsa bo'ladigan** ZET (Telegram orqali buyruq → reja → tasdiq → bajarish →
tekshirish → hisobot, xotira bilan) — **Bo'lim 5 oxirida, ≈ 13–17 hafta**.
