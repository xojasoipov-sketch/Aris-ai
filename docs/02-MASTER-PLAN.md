# ZET — Master Plan (12 bo'lim / 18 faza)

> ⚠️ **Ketma-ketlik yangilandi.** Egasining cheklovlari (`C-01…C-07`) asosida
> bo'limlar tartibi qayta tuzildi va MVP nuqtasi belgilandi:
> [`04-CONSTRAINTS.md`](04-CONSTRAINTS.md). Quyidagi jadval **asl** tartibni saqlaydi
> (har bir bo'limning qamrovi o'zgarmagan) — faqat **bajarilish tartibi** o'zgardi.

> Prinsip (V-44/V-45): **hammasini birdan qurma.**
> Har bir bo'lim oxirida 4 ta artefakt majburiy: **Implementation · Tests · Verification · Documentation.**
> Bo'lim tugamaguncha keyingisi boshlanmaydi.

---

## Bo'limlar xaritasi

| Bo'lim | Fazalar | Nomi | Natija (nima ishlaydi) | Baho |
|---|---|---|---|---|
| **1** | P0, P1 | **Poydevor + Z Core** | CLI/API orqali buyruq → intent → reja → tasdiq → bajarish → tekshirish → trace + xarajat | 3–4 hafta |
| 2 | P2 | Xotira | 7 qatlamli xotira, semantik qidiruv, Obsidian sinxron | 2–3 hafta |
| 3 | P3, P4 | Tool Registry + Agent Runtime | Ro'yxatga olingan toollar, ruxsat bilan; 1-agent (Research) ishlaydi | 3–4 hafta |
| 4 | P5 | Agent Factory | Buyruq bilan yangi agent yaratish, eval, lifecycle | 2–3 hafta |
| 5 | P6 | Telegram + Voice | Telegram = to'liq boshqaruv paneli, ovozli buyruq | 2–3 hafta |
| 6 | P7 | Biznes agentlari | SMM, Sales, Finance, Support | 4–5 hafta |
| 7 | P8, P9 | Developer/GitHub + Internet | PR/issue ishlash; xavfsiz web research | 4–5 hafta |
| 8 | P10, P11 | Qurilmalar + Kamera/Vision | Telefon/kompyuter boshqaruvi, kameralar | 5–7 hafta |
| 9 | P12 | Automation Engine | Trigger→…→Next action, Business Factory | 3–4 hafta |
| 10 | P13 | Dashboard + Mini App | Mockup'dagi to'liq UI | 4–6 hafta |
| 11 | P14, P15 | Xavfsizlik + Testlash | Hardening, pentest, e2e, yuk testi | 3–4 hafta |
| 12 | P16, P17 | Production + Scale | Deploy, backup, kunlik avtonomiya, self-improvement | 3–4 hafta |

---

## Bo'lim 1 — Poydevor + Z Core (P0 + P1) ⬅️ **HOZIR**
To'liq tafsilot: **`03-SECTION-1.md`**

Qamrov: repo skeleti, toolchain, Docker dev muhiti, DB sxemasi, LLM abstraksiyasi,
Model Router v1, Intent → Planner → Router(stub) → Executor → Verifier,
ruxsat modeli + approval gate + emergency stop, observability + cost ledger,
FastAPI + SSE, CLI, testlar + CI, arxitektura hujjati.

**Bo'lim 1 Definition of Done:**
`z run "Ertaga soat 10:00 ga uchrashuv eslatmasini yoz"` →
intent aniqlanadi → reja tuziladi → `note.write` tooli chaqiriladi →
natija tekshiriladi → trace + xarajat bazaga yoziladi → hisobot qaytadi.
`z run "barcha fayllarni o'chir"` → `EXECUTE` darajasi → **approval so'raladi va kutiladi**.

---

## Bo'lim 2 — Xotira (P2)
- 7 qatlam (`short_term`, `conversation`, `task`, `project`, `business`, `personal`, `knowledge`)
- pgvector + hybrid search (BM25 + vektor), reranking
- Memory yozish siyosati: nima eslab qolinadi, nima unutiladi (TTL, summarization)
- Versiyalash, o'chirish, ruxsatga bog'liq ko'rinish (V-14)
- Obsidian 2-tomonlama sinxron (markdown + frontmatter + backlink)
- **DoD:** "O'tgan hafta qanday qaror qabul qilgan edim?" → to'g'ri qatlamdan manba bilan javob

## Bo'lim 3 — Tool Registry + Agent Runtime (P3, P4)
- Tool interfeysi: `name, description, json_schema, permission_level, trust_output, idempotent, timeout`
- Registry: ro'yxatga olish, versiya, allowlist, rate limit, dry-run
- Agent = DB yozuvi (A-02), runtime: context assembly → tool loop → verify → report
- Lifecycle avtomati (V-11), agent metrikalari
- Birinchi agent: **Research** (read-only)
- **DoD:** Research Agent mustaqil vazifani bajarib, manbalar bilan hisobot beradi

## Bo'lim 4 — Agent Factory (P5)
- V-10 oqimi to'liq; mavjud agentlarni tekshirish (dublikat oldini olish)
- Avtomatik eval to'plami generatsiyasi + `TESTING` bosqichi
- `ACTIVATE` faqat egasi tasdig'i bilan
- CEO va Operations agentlari
- **DoD:** "Z, YouTube analitikasini kuzatadigan agent yarat" → DRAFT→TESTING→(tasdiq)→ACTIVE

## Bo'lim 5 — Telegram + Voice (P6)
- aiogram 3 bot, owner allowlist, inline approval tugmalari
- Text / voice / image / file kirish (V-17)
- STT (whisper) → Core; TTS javob
- Push: alerts, task results, reports, agent notifications
- **DoD:** Faqat telefon orqali to'liq ish sikli boshqariladi

## Bo'lim 6 — Biznes agentlari (P7)
- SMM (research→content→schedule→publish→analytics), Sales (lead→CRM→pipeline),
  Finance (tracking + **majburiy approval**), Support (Telegram + escalation)
- Minimal CRM sxemasi; ijtimoiy tarmoq konnektorlari (faqat rasmiy API)
- **DoD:** Bitta haqiqiy biznes jarayoni uchdan-uchgacha avtomatlashadi

## Bo'lim 7 — Developer/GitHub + Internet (P8, P9)
- GitHub App: issue→analyze→plan→PR; CI natijalarini o'qish
- Web search + reader; **A-05 untrusted chegara to'liq amalda**
- Competitor/news monitoring
- **DoD:** Injection test to'plami 100% bloklanadi; Developer Agent real PR ochadi

## Bo'lim 8 — Qurilmalar + Kamera/Vision (P10, P11)
- Android companion app (Kotlin), QR pairing, capability token (A-06)
- Desktop agent daemon (imzolangan buyruqlar, allowlist)
- `ICameraProvider`: Mock → RTSP → EZVIZ; go2rtc gateway
- Motion/person detection, zones, rules; Vision Agent (OCR, screen, doc)
- **DoD:** "Kamerada nima bo'ldi?" → snapshot + tahlil; "Ekranimda nima bor?" → javob

## Bo'lim 9 — Automation Engine (P12)
- Trigger (schedule/webhook/event/manual/agent) → condition → action grafi
- Retry, timeout, failure recovery, approval, notifications (V-27)
- A-07 tormozlari: depth, budget, cooldown, concurrency
- Business Factory: workflow shablonlari
- **DoD:** Kunlik 08:00 briefing avtomatik ishlaydi va xatolikdan tiklanadi

## Bo'lim 10 — Dashboard + Mini App (P13)
- Design system (F-02 hal qilingan token'lar asosida)
- Barcha panellar (V-37/38), assistant holatlari (V-39), zarrachali vizual (V-41)
- Telegram Mini App (V-40)
- **DoD:** Mockup bilan vizual taqqoslash o'tadi; realtime agent statuslari ishlaydi

## Bo'lim 11 — Xavfsizlik + Testlash (P14, P15)
- Threat model, secret rotation, mTLS, rate limit, WebAuthn
- Audit log immutability, emergency stop drill
- e2e (Playwright), yuk testi, chaos test, injection suite
- **DoD:** Xavfsizlik cheklisti 100%; kritik yo'llar test qamrovi ≥ 80%

## Bo'lim 12 — Production + Scale (P16, P17)
- VPS deploy, Caddy, backup/restore mashqi, monitoring/alert
- Kunlik avtonomiya jadvali (V-35)
- Self-improvement halqasi (V-36) — faqat **tavsiya**, avtomatik o'zgarish yo'q
- **DoD:** 30 kun uzluksiz ishlash, RTO < 1 soat, oylik xarajat hisoboti
