# ADR-0006 — Model Strategy va Budjet Rejimi

- **Status:** Qabul qilindi (2026-08-11)
- **Sabab:** Egasi budjeti — hozircha **free API + ~$10/oy**, keyinchalik oshiriladi
- **O'zgartiradi:** `ADR-0001` ning LLM qismini
- **Bog'liq xavf:** `R-02` (xarajat portlashi), `R-06` (vendor lock)

## Kontekst — arifmetika

Bitta to'liq `run` (intent → plan → 3 tool sikli → verify) taxminan:

```
kirish  ≈ 25 000 token
chiqish ≈  3 600 token
```

E'lon qilingan narxlar bo'yicha taxminiy hisob (aniq qiymatlar `pricing.py` da yuritiladi):

| Model sinfi | Taxminiy 1 run narxi | $10 ga necha run |
|---|---|---|
| Kuchli model (Opus darajasi) | ~$0.60 | ~16 |
| Standart model (Sonnet darajasi) | ~$0.13 | **~77** |
| Arzon model (Haiku darajasi) | ~$0.04 | ~230 |

**Muammo:** vision'dagi kunlik avtonomiya (V-35) — 08:00 briefing, 09:00 business
monitoring, 12:00 SMM, 18:00 task report, 21:00 daily summary = **kuniga 5 run,
oyiga 150 run.** Bu — siz birorta buyruq yozmasingizdan oldin.

> Standart modelda kunlik avtonomiyaning o'zi $10 budjetni **oyning 15-kunida** tugatadi.
> Arzon modelda esa oyiga sizga atigi ~80 run qoladi (kuniga 2–3 ta buyruq).

Xulosa: **to'lovli modelni asosiy ish oti qilib bo'lmaydi.** Budjet siyosati keyingi
optimizatsiya emas, arxitekturaning birinchi kunidagi qarori.

## Qaror

### 1. Model Router 4 provayderli bo'ladi, 2 ta emas

| Tier | Provayder | Ishlatilishi | Narx |
|---|---|---|---|
| **T0 — Local** | Ollama (Qwen3 / Llama) | `simple`, klassifikatsiya, summarization, embeddings | **$0** (egasining kompyuterida) |
| **T1 — Free tier** | Google AI Studio (Gemini Flash), Groq, **Mistral** | `normal`, `vision`, tool loop'ning ko'p qismi | **$0** (kvota chegarasida) |
| **T2 — Arzon to'lovli** | Claude Haiku 4.5 | T0/T1 sifat bermagan `normal` vazifalar | ~$0.04/run |
| **T3 — Kuchli to'lovli** | Claude Sonnet 5 / Opus 5 | Faqat `complex` planner va murakkab kod | Qattiq kunlik cheklov ostida |

Marshrutlash tartibi: **T0 → T1 → T2 → T3.** Har bir tier faqat quyidagi hollarda
yuqoriga eskalatsiya qiladi: kvota tugagan · model sifat chegarasidan o'tmagan ·
vazifa aniq `complex` deb belgilangan.

**Aniqlashtirish (implementatsiyada).** T0 va T1 ikkalasi ham bepul, shuning uchun
ular orasidagi tartib **narx bo'yicha emas, sifat bo'yicha** tanlanadi:

| Vazifa sinfi | Birinchi nomzod | Nega |
|---|---|---|
| `simple` | T0 (lokal `qwen3:8b`) | Klassifikatsiya/xulosa uchun yetarli, tarmoq ham kerak emas |
| `normal` | T1 (Gemini Flash) | Bulutli free tier lokal 8B dan sezilarli kuchli, narxi bir xil — $0 |
| `complex` / `coding` | T3 (Sonnet) | **Ataylab qilingan istisno**: planner sifati butun run natijasini belgilaydi. Kunlik 5 chaqiruv chegarasi va bepul zaxira bilan himoyalangan |

Buzilmaydigan invariant (test bilan majburlangan):
**bepul modeldan oldin pullik model turishi mumkin emas** — `complex`/`coding` dan tashqari.

### 2. `simple`/`normal` uchun ovoz va embedding — lokal

| Vazifa | Yechim | Narx |
|---|---|---|
| STT (ovozli buyruq) | `faster-whisper` lokal | $0 |
| Embeddings (Bo'lim 2 xotira) | `bge-m3` / `nomic-embed` lokal (Ollama) | $0 |
| TTS | Lokal (Piper) yoki ElevenLabs faqat so'ralganda | $0 / kam |

### 3. Kvota menejeri — xarajat hisobchisi bilan bir qatorda

Free tier'lar **pulda emas, so'rovlar sonida** cheklanadi (RPM / RPD).
Shuning uchun `cost_ledger` yetarli emas; `QuotaManager` qo'shiladi:

```
quota_ledger(provider, window, used, limit, resets_at)
```

Router qaror qabul qilishdan oldin **ikkalasini ham** tekshiradi:
qolgan USD budjeti **va** qolgan free-tier kvotasi.

### 4. Qattiq chegaralar (fail-closed)

| Chegara | Boshlang'ich qiymat |
|---|---|
| `ZET_BUDGET_MONTHLY_USD` | `10.00` |
| `ZET_BUDGET_DAILY_USD` | `0.50` |
| `ZET_RUN_MAX_USD` | `0.10` |
| T3 (kuchli model) kunlik chaqiruv | `5` |
| Avtonom (jadval bo'yicha) run'lar uchun ajratilgan ulush | Kunlik budjetning `40%` dan ko'p emas |

Chegaraga yetganda: yangi run **rad etiladi** (`BudgetExceeded`), avtonom vazifalar
avval to'xtatiladi, qo'lda yozilgan buyruqlar oxirgi bo'lib to'xtaydi.
Egaga Telegram orqali xabar boradi.

### 5. Kunlik avtonomiya arzonlashtiriladi

Vision'dagi 5 ta jadval vazifasi (V-35) qayta loyihalanadi:
- Ular **bitta `complex` LLM chaqiruvi** bilan emas, avval **deterministik yig'ish**
  (DB so'rovlari, API'lar) + oxirida **bitta arzon model chaqiruvi** bilan yoziladi
- Hech narsa o'zgarmagan bo'lsa — LLM umuman chaqirilmaydi ("no news" holati)

## Oqibatlar

- ✅ ZET $10 budjetda **haqiqatan ishlaydi**, demo emas
- ✅ Kompyuterga ko'chgandan keyin (`ADR-0007`) T0 ulushi oshadi → xarajat yanada tushadi
- ✅ Vendor lock yo'q (`R-06` yopiladi) — 4 provayder bir xil interfeys ostida
- ⚠️ **Z1.5 hajmi oshadi:** 2 provayder o'rniga 4 + `QuotaManager`. +1.5 kun
- ⚠️ Sifat farqi bo'ladi: T0/T1 modellari zaifroq → `Verifier` (Z1.11) muhimroq bo'ladi,
  chunki u past sifatli natijani ushlab, yuqori tier'ga eskalatsiya qiladi
- ⚠️ Free tier shartlari o'zgarishi mumkin → provayder qo'shish/olib tashlash arzon bo'lishi shart

## Budjet oshgandagi migratsiya

Budjet $100/oy ga chiqsa: `.env` da chegaralarni oshirish va `model_policy` da
`normal` ni T1 dan T2 ga surish yetarli. **Kod o'zgarmaydi.**
