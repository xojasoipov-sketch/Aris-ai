# ZET — nima va nima uchun

> Bu fayl loyihaning haqiqiy holatini aks ettiradi (kod bazasidan olingan
> fakt asosida yozilgan) — `README.md`dagi eski "kod hali yozilmagan" degan
> jumlaga qaramang, u yangilanmagan qolib ketgan.

## 1. ZET nima

**ZET — bitta egaga tegishli shaxsiy AI operatsion tizim.** Ommaviy SaaS
emas, ko'p foydalanuvchili mahsulot emas — bitta odam (ega) uchun ishlaydi
va uning butun raqamli hayotini (vazifalar, loyihalar, kalendar, fayllar,
ijtimoiy tarmoqlar, savdo, mijozlar, qurilmalar) bitta joydan boshqarish
uchun mo'ljallangan.

Farqi oddiy chatbotdan:

```
Oddiy AI:  Foydalanuvchi → Savol → Javob
ZET:       Foydalanuvchi → Buyruq → Reja → Harakat → Tekshirish → Natija
```

Ya'ni ZET faqat javob bermaydi — **reja tuzadi, ish bajaradi, natijani
tekshiradi va hisobot beradi**. Nomi tarixiy jihatdan "JARVIS" kontseptidan
kelib chiqqan (Iron Man'dagi AI yordamchi g'oyasi), lekin kodda "JARVIS"
so'zi ishlatilmaydi — mahsulot nomi rasman **ZET**.

## 2. Nima uchun yaratilgan

Egasining o'zi kuzatib, boshqarib bo'lmaydigan ko'p sonli takrorlanuvchi
ishlarni (kunlik hisobotlar, mijozlarga javob, kontent rejasi, tizim
monitoring) avtonom, lekin **nazorat ostida** bajaradigan yordamchi kerak
edi. Asosiy printsiplar:

- **Xavfsizlik birinchi** — har bir xavfli amal (pul, xabar yuborish,
  kodga o'zgartirish) approval (tasdiqlash) darvozasidan o'tadi
- **Halollik** — soxta "muvaffaqiyat" yo'q; tool ishlamasa aniq xato,
  backend ulanmagan bo'lsa aniq "ulanmagan" holati ko'rsatiladi
- **Byudjet nazorati** — LLM chaqiruvlariga qattiq oylik/kunlik/run
  chegarasi, oshsa run avtomatik rad etiladi (fail-closed)
- **Bosqichma-bosqich** — hech narsa "hammasi birdan" qurilmagan; har bir
  bo'lim implementation + test + verification + documentation bilan yopiladi

## 3. Asosiy arxitektura

```
Foydalanuvchi (CLI/API/Web/Telegram)
        │
        ▼
Command → Intent Recognition → Planner → Approval → Executor → Verifier
        │                                    │            │
        │                              PermissionPolicy   ToolRegistry
        │                              (READ<WRITE<        (allowlist,
        │                               EXECUTE<ADMIN)      JSON Schema)
        ▼
   Model Router (4 tier)
   T0 lokal (Ollama, bepul) → T1 free tier (Gemini/Groq/Mistral)
   → T2 arzon (Haiku) → T3 kuchli (Sonnet/Opus)
```

**Trust darajalari** (xavfsizlik chegarasi): `OWNER` (ega) → `SYSTEM`
(ZET'ning o'zi) → `UNTRUSTED` (tashqi manba — masalan GitHub issue matni,
web sahifa kontenti). Untrusted kontentdagi "buyruqlar" hech qachon
bajarilmaydi — bu injection'dan himoya.

**Risk darajalari**: `LOW → MEDIUM → HIGH → CRITICAL` — qanchalik xavfli
amal, shunchalik qattiq tasdiqlash talab qilinadi.

## 4. Backend (`apps/core`) — nima qila oladi

Python 3.12 + FastAPI + Postgres/pgvector (yoki dev'da SQLite) + Redis.

**Agentlar** (`agents/builtin/`) — har biri o'z ruxsat darajasi va tool
ro'yxati bilan:

| Agent | Vazifasi |
|---|---|
| `research` | Web qidiruv + GitHub repo/arxitektura tahlili, faqat READ |
| `developer` | GitHub issue/PR boshqaruvi, kod o'zgarishi, CI kuzatuv |
| `ceo` | Strategik qarorlar, boshqa agentlarga topshiriq |
| `sales` / `support` | Mijozlar bilan ishlash (CRM) |
| `hr` | AI ishchi kuchini boshqarish |
| `qa` | Sifat nazorati |
| `ecommerce` | Mahsulot katalogi, buyurtma |
| `finance` | Moliyaviy hisob-kitob |
| `operations` | Kunlik operatsion vazifalar |
| `security` | Xavfsizlik monitoring |
| `smm` | Ijtimoiy tarmoq boshqaruvi |
| `analytics` | Hisobot va tahlil |
| `vision` | Rasm/video tahlil (OCR, kamera) |

**Tool tizimi** (`tools/builtin/`, 25+ tool) — GitHub, Instagram, YouTube,
Telegram, kamera (Hikvision), desktop boshqaruv, workspace (loyiha/vazifa/
kalendar), CRM, commerce, memory (yozish/qidiruv), video o'rganish,
public-apis kashfiyoti, va h.k. Har bir tool `ToolRegistry`ga ro'yxatdan
o'tadi va faqat unga ruxsat berilgan agent chaqira oladi.

**Integratsiyalar** (`integrations/`):
- `public_apis` — public-apis.dev katalogidan xavfsiz API kashfiyoti
  (faqat discovery, avtomatik ishga tushirish yo'q)
- `github_intel` — 9 ta mashhur GitHub repo (OpenClaw, system-design-primer
  va h.k.) bo'yicha bilim manbai — kod ko'chirilmaydi, faqat metadata +
  arxitektura tahlili

**Ovoz** (`voice/`) — lokal Whisper (STT) + Meta MMS (TTS), o'zbek tili
uchun maxsus sozlangan (lotin↔kirill transliteratsiya bilan).

**Xotira** (`memory/`) — semantik qidiruv (embedding asosida), ega
profilini saqlash, Obsidian vault bilan integratsiya.

**Xavfsizlik** (`security/`): PermissionPolicy (fail-closed), ApprovalService
(TTL bilan, o'zgarmas), KillSwitch (favqulodda to'xtatish).

**192 test fayli**, `ruff` + `mypy --strict` yashil.

## 5. Frontend (`apps/web`) — ZET'ning yuzi

Next.js 15 + TypeScript + Tailwind v4. Sahifalar: Boshqaruv (dashboard),
**Nexus** (immersiv AI boshqaruv markazi — signature `<NeuroOrb/>` 3D
zarracha-sfera komponenti orqali), AI Yordamchi (chat), Agentlar,
Loyihalar, Vazifalar, Kalendar, Xabarlar, Fayllar, Analitika, Qurilmalar,
Kamera, Terminal, Sozlamalar, va Telegram Mini App (`/tg`).

Dizayn tizimi qat'iy tokenlashtirilgan (`apps/web/CLAUDE.md`) — deyarli
qora fon (hech qachon toza qora emas), ko'k aksent (`#4C8DFF`), hairline
border'lar, og'ir soya/gradient/emoji **taqiqlangan**. Maqsad — "concept"
emas, Linear/Stripe/Vercel darajasidagi haqiqiy mahsulot hissi.

## 6. Hozirgi holat

- Backend'ning asosiy pipeline'i (Intent→Plan→Approval→Execute→Verify),
  13 ta agent, 25+ tool, xavfsizlik qatlami, xotira, ovoz, Telegram
  integratsiyasi — **ishlab turibdi**
- Frontend — barcha asosiy sahifalar qurilgan, lekin ba'zilari hali
  backend'ga to'liq ulanmagan (task #35, davom etmoqda)
- Deploy: avval Railway'da sinalgan, keyin resurs cheklovlari sababli
  (LLM rate limit, Ollama yo'qligi) **o'z serveringizda (Hetzner) ishga
  tushirish**ga o'tildi (`infra/hetzner/`) — bu variant to'liq CPU/RAM va
  lokal Ollama beradi
- Lokal dev uchun endi bitta buyruq yetarli: `bash scripts/start-local.sh`
  (Docker ixtiyoriy — bo'lmasa SQLite'ga tushadi)

## 7. Nima qilishi kerak (davom etayotgan yo'nalish)

1. Frontend'dagi qolgan sahifalarni haqiqiy backend ma'lumotiga ulash
2. Google API kalitini almashtirish (eskirgan, logda ko'ringan)
3. OpenClaw va System Design Primer auditlaridan chiqqan tavsiyalarni
   (memory yozish xavfsizligi, desktop-tool himoyasi) alohida audit bilan
   amalga oshirish — atayin shu sessiyada qilinmagan, chunki bular
   `memory.write` va `desktop.*` kabi og'ir yuklamali tizimlarga tegadi
4. GitHub Intelligence Layer orqali kelgusi arxitektura qarorlarini
   Research Agent orqali qo'llab-quvvatlash

---
*Bu hujjat qo'lda yozilgan, lekin repo'dagi haqiqiy kod/test/hujjat
holatiga asoslangan (2026-08-28 holatiga ko'ra).*
