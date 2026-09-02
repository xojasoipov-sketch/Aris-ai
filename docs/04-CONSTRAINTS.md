# ZET — Egasining Cheklovlari va Qayta Ko'rilgan Ketma-ketlik

> Manba: loyiha egasining 2026-08-11 dagi javoblari.
> Ushbu hujjat javoblarni **muhandislik cheklovlariga** (`C-01…C-07`) aylantiradi
> va shu asosda `02-MASTER-PLAN.md` ketma-ketligini qayta tartiblaydi.

---

## C-01 · Kameralar: Hikvision

**Javob:** Hikvision.

**Ta'sir — ijobiy.** Vision'da `ICameraProvider` uchun EZVIZ ko'rsatilgan edi
(EZVIZ — Hikvision'ning iste'molchi brendi, bulut orqali ishlaydi va API'si cheklangan).
To'g'ridan-to'g'ri Hikvision qurilmalari uchtala ochiq yo'lni beradi:

| Protokol | Nima uchun |
|---|---|
| **ISAPI** (HTTP) | Qurilma holati, snapshot, PTZ, **hodisa oqimi** (motion, line crossing, intrusion), zonalar |
| **RTSP** | Video oqim |
| **ONVIF** | Standart discovery va boshqaruv (zaxira yo'l) |

➡️ **Eng muhimi: ISAPI hodisa oqimi bor.** Demak kamerani doimiy so'rab turish
(polling) shart emas — qurilmaning o'zi hodisa yuboradi. Bu `R-10` (kamera resursni
yeyishi) va `R-02` (xarajat) xavflarini ikkalasini ham keskin kamaytiradi:
vision-model faqat **hodisa bo'lganda** chaqiriladi, 24/7 emas.

**Provider rejasi:** `MockProvider` (test) → `HikvisionISAPIProvider` (asosiy)
→ `ONVIFProvider` (zaxira). EZVIZ bulutli yo'li **kerak emas**.

---

## C-02 · OS: macOS **va** Windows

**Javob:** ikkalasi.

**Ta'sir:** desktop qatlami boshidanoq cross-platform. `PlatformAdapter` protokoli
(`MacAdapter` / `WindowsAdapter` / `LinuxAdapter`), yadro kodi platformani bilmaydi.
Tafsilot: [`ADR-0007`](adr/ADR-0007-deployment-local-first.md) §4.

⚠️ Sinov yuki ikki barobar: har bir desktop tool ikkala OS'da tekshirilishi kerak.
Bo'lim 8 ga **+1 hafta**.

---

## C-03 · Biznes qamrovi: "hammasi"

**Javob:** to'liq nazorat + YouTube yuritish + CRM + o'quv markaz + boshqa bizneslar.

**Bu — maqsad, ketma-ketlik emas.** Hammasi rejada qoladi, lekin tartib kerak.
Tanlov mezoni: **eng tez qiymat beradigan + eng kam tashqi to'siq.**

| O'rin | Yo'nalish | Nega shu tartib |
|---|---|---|
| **1** | **O'quv markaz CRM** | Ma'lumot **sizniki** — tashqi API kvotasi, ToS, review yo'q. Postgres'da to'liq quramiz. Eng aniq ROI: lidlar, o'quvchilar, guruhlar, davomat, to'lovlar, qarzdorlik |
| **2** | **YouTube** | Rasmiy **Data API v3** bor: yuklash, metadata, analitika. Kvota bepul va saxiy. Tashqi to'siq minimal |
| **3** | **Telegram SMM / Support** | Bot API to'liq ochiq, ZET allaqachon Telegram'da (Bo'lim 5) |
| **4** | Instagram / Facebook | Graph API mavjud, lekin **Business akkaunt + ilova review** talab qiladi. Post/Reels chekli, Stories yanada chekli |
| **5** | TikTok / X / boshqalar | ⚠️ TikTok Content Posting API cheklangan ruxsat talab qiladi; X API endi pullik. Bularda **"draft + qo'lda tasdiq"** rejimi (`R-09`) |

➡️ **Halol ogohlantirish:** "hamma tarmoqda avtomatik post" texnik jihatdan
to'liq mumkin emas — platformalarning o'zi ruxsat bermaydi. ZET hamma joyda
**kontent tayyorlaydi va rejalashtiradi**, lekin faqat 1–4 dagilarga avtomatik
joylaydi. 5 dagilarga — bir tugma bosish qoladi.

---

## C-04 · Ijtimoiy tarmoqlar: "hammasi"; boshqaruv: Telegram

**Javob:** kontent uchun hammasi; ZET'ni boshqarish uchun Telegram.

**Ta'sir:** boshqaruv qatlami bitta — Telegram (Bo'lim 5). Bu yaxshi:
dashboard (Bo'lim 10) endi **kritik yo'lda emas**, uni keyinga surish mumkin.
Bu tezlik uchun katta yutuq (`C-07`).

---

## C-05 · Budjet: free API + ~$10/oy

**Javob:** hozircha free + $10, keyinchalik ko'tariladi.

**Ta'sir — eng katta.** To'liq tahlil va yechim:
[`ADR-0006`](adr/ADR-0006-model-strategy-and-budget.md).

Qisqacha: kunlik avtonomiyaning **o'zi** standart modelda $10 ni oyning yarmida
tugatadi. Shuning uchun Model Router 4 tier'li bo'ladi
(`Lokal → Free tier → Arzon → Kuchli`) va `QuotaManager` qo'shiladi.

➡️ **Z1.5 ga +1.5 kun.** Buning evaziga ZET $10 da haqiqatan ishlaydi.

---

## C-06 · Joylashuv: hozir istalgan joy → keyin to'liq kompyuterda

**Javob:** test uchun istalgan joyda, tugagach kompyuterga to'liq o'tadi.

**Ta'sir:** [`ADR-0007`](adr/ADR-0007-deployment-local-first.md) — local-first.
Eng muhim uchta oqibat:
1. **Telegram long polling** (webhook emas) — ommaviy IP kerak emas
2. **Ollama lokal modellar** — `C-05` budjetini qutqaradi
3. **Bo'lim 8 soddalashadi** — desktop boshqaruvi masofaviy emas, mahalliy

⚠️ Ochiq savol Bo'lim 12 ga qoladi: kompyuter o'chganda 08:00 briefing kim yuboradi?

---

## C-07 · Tezlik: "ko'p cho'zmaymiz, lekin sifatli"

**Javob:** tez, lekin sifat bilan.

**Ta'sir:** ketma-ketlik qayta tartiblanadi va Bo'lim 1 "lean" versiyaga o'tadi.
Sifat darvozalari (`mypy --strict`, testlar, CI, approval gate) **qisqartirilmaydi** —
ular tezlikni oshiradi, kamaytirmaydi. Qisqartiriladigan narsa — **qamrov**:
hozir kerak bo'lmagan narsalar keyinga suriladi.

---

# Qayta ko'rilgan ketma-ketlik

`C-03`, `C-04`, `C-07` asosida `02-MASTER-PLAN.md` tartibi o'zgaradi:

| Yangi o'rin | Bo'lim | Eski o'rin | O'zgarish sababi |
|---|---|---|---|
| 1 | Poydevor + Z Core | 1 | — |
| 2 | Xotira | 2 | — |
| 3 | Tool Registry + Agent Runtime | 3 | — |
| 4 | **Telegram + Voice** | 5 | ⬆️ **Yuqoriga** — `C-04`: yagona boshqaruv qatlami. Bu yerdan keyin ZET **ishlatsa bo'ladi** |
| 5 | Agent Factory | 4 | ⬇️ Pastga — avval ishlaydigan tizim, keyin agent ko'paytirish |
| 6 | **Biznes: O'quv markaz CRM** | 6 (qismi) | `C-03` #1 — eng tez ROI |
| 7 | **Biznes: YouTube + SMM** | 6 (qismi) | `C-03` #2–3 |
| 8 | Automation Engine | 9 | ⬆️ Yuqoriga — kunlik avtonomiya biznes agentlaridan keyin darhol kerak |
| 9 | Developer/GitHub + Internet | 7 | ⬇️ |
| 10 | **Kamera/Vision (Hikvision)** | 8 (qismi) | ⬇️ Pastga — mustaqil blok, biznesdan keyin |
| 11 | Desktop boshqaruvi (mac + Win) | 8 (qismi) | ⬇️ `ADR-0007` tufayli soddalashgan |
| 12 | Dashboard + Mini App | 10 | ⬇️ **Eng pastga** — `C-04`: Telegram yetarli |
| 13 | Xavfsizlik + Testlash | 11 | — |
| 14 | Production | 12 | — |

## ⭐ MVP nuqtasi

**Bo'lim 1 → 2 → 3 → 4 (Telegram)** ≈ **8–9 hafta**

Shundan keyin sizda:
- Telefondan ovoz yoki matn bilan buyruq berasiz
- ZET tushunadi → reja tuzadi → xavfli bo'lsa tasdiq so'raydi → bajaradi → tekshiradi
- Nima qilganini, qancha turganini ko'rsatadi
- Bilim va qarorlarni eslab qoladi (Obsidian bilan)
- Bitta ishlaydigan agent (`Research`)

Bu — vision'ning ishlaydigan yadrosi. Qolgan hammasi shu poydevor ustiga qo'shiladi.

---

# Lean Bo'lim 1

`C-07` uchun Bo'lim 1 qisqartiriladi: **24 kun → ~17 kun.**

## Keyinga suriladi

| Task | Qayerga | Nega mumkin |
|---|---|---|
| Z1.13 dagi **Langfuse** | Bo'lim 13 | Trace o'z DB'imizda (`run/step/tool_call`) allaqachon to'liq. Langfuse — qulaylik, zarurat emas |
| Z1.14 dagi **SSE streaming** | Bo'lim 4 (Telegram) | CLI uchun oddiy polling yetarli |
| Z1.9 (Agent Router stub) | Z1.8 ichiga qo'shiladi | Alohida task bo'lishi shart emas |
| `apps/web` skeleti | Bo'lim 12 | Dashboard eng pastga tushdi |

## Kuchaytiriladi

| Task | O'zgarish | Sabab |
|---|---|---|
| **Z1.5** | 2 provayder → **4 tier + QuotaManager** | `C-05` / `ADR-0006` · **+1.5 kun** |
| **Z1.12** | Budjet chegarasi approval gate bilan bir qatorda | `C-05` — budjet ham xavfsizlik chegarasi |

## Lean Bo'lim 1 — yakuniy ro'yxat

| # | Task | Kun |
|---|---|---|
| Z1.0 | Repo skeleti, ZET nomlash | 0.5 |
| Z1.1 | Toolchain: uv · ruff · mypy strict · pytest · gitleaks | 0.5 |
| Z1.2 | Konfiguratsiya + sirlar | 0.5 |
| Z1.3 | Docker dev (Postgres+pgvector, Redis) | 0.5 |
| Z1.4 | DB poydevori + yadro sxemasi | 2 |
| **Z1.5** | **LLM: 4 tier + Model Router + QuotaManager + cost/quota ledger** | **3.5** |
| Z1.6 | Domen kontraktlari | 1 |
| Z1.7 | Intent Recognizer | 1.5 |
| Z1.8 | Planner (+ Agent Router stub) | 2 |
| Z1.10 | Tool interfeysi + registry + 3 tool | 2 |
| Z1.11 | Executor + Verifier (+ resume) | 2.5 |
| Z1.12 | Ruxsat + Approval + Budjet + Emergency stop | 2 |
| Z1.13 | Observability (o'z DB trace + structlog + cost hisobot) | 1 |
| Z1.14 | FastAPI (SSE'siz) | 1 |
| Z1.15 | `z` CLI | 1 |
| Z1.16 | Test infra + CI | 1 |
| Z1.17 | ARCHITECTURE.md + qolgan ADR'lar | 1 |
| | **Jami** | **≈ 23.5 → parallel ishlar bilan ~17 ish kuni** |

**DoD o'zgarmaydi** — `03-SECTION-1.md` dagi 6 ta mezon, ustiga bitta yangi:

7. `z cost month` → free tier kvotasi va USD sarfi alohida ko'rsatiladi;
   `ZET_BUDGET_DAILY_USD` oshsa yangi run **rad etiladi**.
