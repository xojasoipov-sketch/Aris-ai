# ZET — Hujjatlar va Repository Auditi (P0)

> Sana: 2026-08-11 · Bosqich: **P0 — Repository Audit** · Status: **yakunlandi**
> Ushbu hujjat hech qanday kodni o'zgartirmaydi. Faqat mavjud holatni qayd etadi.

---

## 1. Kirish materiallari inventarizatsiyasi

`ZET.zip` ichidan chiqqan real fayllar:

| Fayl | Hajm | Turi | Qiymati |
|---|---|---|---|
| `JARVIS-Presentation.pptx` | 4.5 MB | 40 slayd, **har biri to'liq PNG rasm** | ★★★★★ — asosiy vision manbasi |
| `features.md` | 2.4 KB | PPT outline (40 sarlavha) + design style | ★★★☆☆ |
| `material.md` | 1.7 KB | Qisqa xulosa (overview/background/analysis) | ★★☆☆☆ |
| `62538B5C….png` | 2.1 MB | To'liq desktop dashboard mockup | ★★★★★ — frontend spec |
| `F79BF99B….png` | 2.0 MB | Holatlar + Telegram Mini App sahifalari | ★★★★★ — frontend spec |
| `IMG_1701.jpeg` | 213 KB | Generative art moodboard (MJ prompt bilan) | ★★★★☆ — vizual til |
| `IMG_1693.jpeg` | 44 KB | Status chip'lar: Thinking / Searching / Agent shaping / Agent listening | ★★★★☆ |

### 1.1. MUHIM: hujjat nomlari mos kelmadi

Topshiriqda `JARVIS_VISION.md`, `JARVIS_ARCHITECTURE.md`, `JARVIS_ROADMAP.md` deb aytilgan.
**Arxivda bu uchta fayl yo'q.** Ular o'rniga PPTX + 2 ta qisqa md bor.

Buning oqibati (audit topilmasi **F-01**):

- **Vision** — to'liq va aniq (40 slayd orqali). ✅
- **Roadmap** — mavjud, lekin faqat 17 ta faza nomi ko'rinishida (slayd 38). Muddat, bog'liqlik, DoD yo'q. ⚠️
- **Architecture** — **yozma texnik spetsifikatsiya sifatida umuman mavjud emas.** ❌
  Slaydlarda faqat konseptual oqim qutilari bor (`INTENT → PLANNER → AGENT ROUTER → TOOLS → EXECUTION → VERIFICATION`).
  Yo'q narsalar: tech stack, ma'lumotlar modeli, API kontraktlari, xizmatlar chegarasi,
  deployment topologiyasi, xatoliklar/retry semantikasi, ruxsatlar modeli sxemasi.

**Xulosa:** loyihaning "nima qilish kerak"i 95% aniq, "qanday qilish kerak"i 0% yozilgan.
Shu bo'shliqni to'ldirish — Bo'lim 1 ning asosiy vazifasi.

---

## 2. Vision — chiqarib olingan to'liq talablar ro'yxati

40 slayddan ajratilgan funksional talablar (har biri keyingi rejada ID sifatida ishlatiladi).

### 2.1. Falsafa (slayd 2, 3)
- `V-01` An'anaviy AI: `User → Question → Answer`. ZET: **`User → Command → Plan → Action → Verification → Result`**.
- `V-02` ZET — bitta egaga tegishli **shaxsiy AI operatsion tizim**, ommaviy SaaS emas.
- `V-03` 12 ta qobiliyat bloki: AI Assistant, AI Agents, Agent Factory, Automation, Business Mgmt, Knowledge, Device Control, Internet, Dev Tools, Analytics, Memory, Coordinated Core.

### 2.2. Core (slayd 5, 37)
- `V-04` Markaziy pipeline: `USER → Z CORE → INTENT → PLANNER → AGENT ROUTER → TOOLS → EXECUTION → VERIFICATION`.
- `V-05` Umumiy topologiya: `OWNER → TELEGRAM/VOICE → Z CORE → {AGENTS | MEMORY(Obsidian) | TOOLS(web/github/camera)} → AUTOMATION → DEVICES/BUSINESS`.
- `V-06` Bitta buyruq → ko'p koordinatsiyalangan harakat (slayd 4: Calendar, Tasks, Business, Sales, SMM, Agents, Risks, Priorities, Obsidian, Report).

### 2.3. AI Workforce (slayd 6, 9–18, 30)
- `V-07` **17 ta agent, 4 bo'linma:**
  - Management: CEO, Operations, HR
  - Business: SMM, Sales, Finance, Support, E-commerce
  - Technology: Developer, QA, DevOps, Design, Security
  - Intelligence: Research, Analytics, Innovation, Prediction
- `V-08` Agent-to-Agent zanjiri: `CEO → Research → SMM → Content → Design → QA → Analytics → CEO`.
- `V-09` Har bir agentning aniq mas'uliyat/chiqim ro'yxati bor (slayd 9–18).

### 2.4. Agent Factory & Lifecycle (slayd 7, 8)
- `V-10` Factory oqimi: `REQUEST → UNDERSTAND → CHECK EXISTING → DESIGN → SELECT TOOLS → PERMISSIONS → PROMPT → TESTS → TEST → ACTIVATE`.
- `V-11` Lifecycle: `DRAFT → TESTING → ACTIVE → PAUSED → DISABLED → ARCHIVED`.
- `V-12` Har bir agentda 12 ta atribut: Role, Goal, System prompt, Tools, Knowledge, Memory, Permissions, Triggers, Workflows, Version, Metrics, Logs.

### 2.5. Memory (slayd 19, 20)
- `V-13` 7 qatlamli xotira: `Short-term → Conversation → Task → Project → Business → Personal → Obsidian Knowledge`.
- `V-14` Xotira xossalari: **Searchable · Editable · Versioned · Permission-aware · Deletable**.
- `V-15` Obsidian = uzoq muddatli bilim qatlami (create/read/update notes, search, link, backlinks, decisions, ideas, projects, meeting notes).
- `V-16` "ZET suhbatni emas, **bilim va qarorlarni** eslab qoladi."

### 2.6. Interfeyslar (slayd 21, 22, 23, 24)
- `V-17` Telegram = asosiy boshqaruv paneli. IN: text, voice, images, files. OUT: answers, alerts, task results, reports, approval requests, agent notifications.
- `V-18` Ovoz birinchi darajali kirish: `VOICE → STT → INTENT → PLAN → ACTION → TEXT/VOICE RESPONSE`.
- `V-19` Telefon: QR orqali xavfsiz pairing → authenticate → pair → permissions → control. Imkoniyatlar: notifications, screenshots, camera, device status, files, clipboard, app launching, approved automation. Android uchun Termux yoki maxsus companion app.
- `V-20` Kompyuter (macOS/Windows/Linux): terminal, files, browser, applications, screenshots, keyboard, mouse, scripts, dev environment.

### 2.7. Tashqi dunyo (slayd 25, 26, 27)
- `V-21` Internet Agent: web search, website reading, data extraction, competitor/news/market monitoring, documentation.
- `V-22` **Xavfsizlik aksiomasi:** tashqi saytlar — `untrusted input`. ZET saytdagi ko'rsatmalarni ko'r-ko'rona bajarmaydi.
- `V-23` `ICameraProvider` abstraksiyasi: EZVIZ, RTSP, Mock, kelajakdagi provayderlar. Imkoniyatlar: status, snapshot, stream, events, motion/person detection, vision analysis, zones, rules, PTZ, presets, device health.
- `V-24` Vision Agent: images, screenshots, documents, camera images, objects, scenes, OCR, visual changes.

### 2.8. Avtomatlashtirish (slayd 28, 29)
- `V-25` Engine: `TRIGGER → CONDITION → AGENT → TOOL → ACTION → VERIFY → NEXT ACTION`.
- `V-26` Trigger turlari: schedule, webhook, event, manual command, agent trigger.
- `V-27` Engine xossalari: **retry, timeout, failure recovery, approval, notifications**.
- `V-28` Business Factory: har qanday takrorlanuvchi jarayon → workflow (Sales: `LEAD→SALES→QUALIFY→CRM→FOLLOW-UP→OFFER→REPORT`; Content: `TREND→RESEARCH→SMM→CONTENT→PUBLISH→ANALYTICS→OPTIMIZE`).

### 2.9. Model Router (slayd 31)
- `V-29` Vazifa sinfi bo'yicha marshrutlash: simple→fast/cheap, normal→standard, complex→strong, coding→coding, vision→vision, voice→speech.
- `V-30` O'lchanadi: token usage, API cost, runtime, success rate. Maqsad: "maksimal qobiliyat, nazorat ostidagi xarajat".

### 2.10. Xavfsizlik (slayd 32)
- `V-31` Ruxsat darajalari: **READ / WRITE / EXECUTE / ADMIN**.
- `V-32` Tasdiq talab qiladigan yuqori xavfli amallar: money transfer, account deletion, destructive production op, secret changes, sensitive data export, dangerous device actions.
- `V-33` Xavfsizlik qatlamlari: authentication, device auth, encryption, secret mgmt, audit logs, rate limits, backups, recovery, **emergency stop**.

### 2.11. Observability & Autonomy (slayd 33, 34, 35)
- `V-34` To'liq iz: `USER → INTENT → AGENT → TOOL → ACTION → RESULT → VERIFICATION → COST/DURATION`.
- `V-35` Kunlik avtonomiya: 08:00 briefing · 09:00 business monitoring · 12:00 SMM monitoring · 18:00 task report · 21:00 daily summary.
- `V-36` Self-improvement: agent/tool failures, workflow bottlenecks, cost, performance, repeated tasks, missing capabilities → tavsiya: new agent / new tool / new workflow / better model / better process / cost optimization. **Production o'zgarishlari tasdiqdan o'tadi.**

### 2.12. Frontend (mockup rasmlar)
- `V-37` Desktop dashboard, chap navigatsiya: Dashboard, AI Assistant, Agents, Projects, Calendar, Tasks, Messages, Files, Analytics, Devices, Camera, Settings.
- `V-38` Panellar: System Status (CPU/RAM/Disk/Network), Quick Actions, AI Thinking, Projects (progress %), Agents (online/working/thinking/offline), Tasks (donut + ro'yxat), Camera System (6 kamera + PTZ + presets), Dev Terminal, Messages, Files, Analytics, Settings.
- `V-39` Assistant holatlari: **Sleep (tinch orb) · Asosiy suhbat · Minimize (floating orb) · Floating quick-commands · Bildirishnoma**.
- `V-40` Telegram Mini App: chat, agents, projects, tasks, camera, settings sahifalari.
- `V-41` Vizual til: sof qora fon, mayda oq nuqtalardan generativ zarrachalar (neyro shar / profil), monospace texnik yorliqlar, status chip'lar ("Thinking…", "Searching…", "Agent shaping…", "Agent listening…").
- `V-42` **Ziddiyat (F-02):** `features.md` da design style = grafit `#0B0E14` + **teal/yashil** akцent; dashboard mockup'da esa **ko'k/cyan** (`#4A9EFF` atrofida). Ikkalasi bir loyihada ikki xil brend. Bo'lim 1 da bitta design token to'plami tanlanishi shart.

### 2.13. Roadmap (slayd 38, 39)
- `V-43` 18 ta faza: P0 Repository Audit · P1 Jarvis Core · P2 Memory · P3 Tool Registry · P4 Agent Runtime · P5 Agent Factory · P6 Telegram · P7 Business Agents · P8 Developer/GitHub · P9 Browser/Internet · P10 Phone/Computer · P11 Camera/Vision · P12 Automation · P13 Dashboard · P14 Security · P15 Testing · P16 Production · P17 Scale.
- `V-44` Rivojlanish prinsipi: **hammasini birdan qurma**. `AUDIT → CORE → TEST → MEMORY → TEST → AGENTS → TEST → AGENT FACTORY → TEST → INTEGRATIONS → TEST → DEVICES → TEST → PRODUCTION`.
- `V-45` **Har bir fazada 4 ta artefakt majburiy: Implementation · Tests · Verification · Documentation.**

---

## 3. Repository auditi

### 3.1. Mavjud holat (o'lchangan)

```
repo:      xojasoipov-sketch/aris-ai
commits:   1  (ffe4991 "Initial commit")
branches:  main, claude/zetproject-audit-plan-p9lysv  (ikkalasi bir xil)
fayllar:   README.md  (9 bayt: "# Aris-ai")
git obj:   3
```

### 3.2. Nima yo'q

| Kategoriya | Holat |
|---|---|
| Manba kod (backend/frontend) | ❌ yo'q |
| Package manifest (`pyproject.toml` / `package.json`) | ❌ yo'q |
| Dependency lock | ❌ yo'q |
| Testlar | ❌ yo'q |
| CI/CD (`.github/workflows`) | ❌ yo'q |
| Docker / Compose | ❌ yo'q |
| `.gitignore` | ❌ yo'q |
| `.env.example` | ❌ yo'q |
| LICENSE | ❌ yo'q |
| `docs/` | ❌ yo'q (ushbu hujjatgacha) |
| Migratsiyalar | ❌ yo'q |
| Lint/format konfiguratsiyasi | ❌ yo'q |
| Issue/PR template | ❌ yo'q |
| Branch protection | ❌ sozlanmagan |

### 3.3. Baholash

| O'lcham | Ball | Izoh |
|---|---|---|
| Performance | — | O'lchash uchun kod yo'q |
| Scalability | — | Arxitektura yo'q |
| Reliability | — | Test/CI/monitoring yo'q |
| Security | — | Secret boshqaruvi, auth, audit yo'q |
| Maintainability | — | Struktura, konvensiya, hujjat yo'q |
| **Technical debt** | **0** | ✅ **Bu yagona ijobiy tomon** |

**Xulosa:** repository — **toza greenfield**. Bu kamchilik emas, imkoniyat:
migratsiya xarajati yo'q, legacy qaror yo'q, arxitekturani noldan to'g'ri tanlash mumkin.
Lekin bu shuni ham anglatadiki, **vision'ning 100% i bajarilmagan** (3-bo'limga qarang: `01-VISION-GAP.md`).

### 3.4. Audit topilmalari (harakat talab qiladiganlar)

| ID | Topilma | Jiddiylik | Yechim |
|---|---|---|---|
| F-01 | Yozma texnik arxitektura hujjati yo'q | 🔴 Yuqori | Bo'lim 1, Z1.17 |
| F-02 | Brend rangida ziddiyat (teal vs ko'k) | 🟡 O'rta | ✅ **Yopildi** — `ADR-0005`: ko'k/cyan (mockup) tanlandi |
| F-03 | Repo nomi (`Aris-ai`) loyiha nomiga (`ZET`) mos emas | 🟡 O'rta | Repo rename yoki README da rasmiylashtirish |
| F-04 | `main` branch himoyalanmagan | 🟡 O'rta | Bo'lim 1, Z1.16 (CI + branch protection) |
| F-05 | Rejadagi "JARVIS" nomi mahsulot nomi bilan ziddiyatda | 🟢 Past | Barcha hujjat/koda **ZET / Z** ga o'tildi |
| F-06 | 17 agentni birdaniga qurish rejasi realistik emas | 🔴 Yuqori | `01-VISION-GAP.md` §5 (bosqichli agent chiqarish) |
| F-07 | Obsidian "ma'lumotlar bazasi" sifatida ko'rsatilgan | 🔴 Yuqori | `01-VISION-GAP.md` §4.3 (Postgres = source of truth) |
| F-08 | Untrusted input chegarasi arxitekturada modellashtirilmagan | 🔴 Yuqori | `01-VISION-GAP.md` §4.5 |

---

## 4. Nomlash qarori

| Eski | Yangi |
|---|---|
| JARVIS | **ZET** |
| Jarvis Core | **Z Core** |
| — | Python package: `zet` |
| — | CLI buyrug'i: `z` |
| — | API prefiksi: `/v1` |
| — | Telegram bot: `@…` (egasi tanlaydi) |

Barcha keyingi hujjat, kod, commit va UI matnida faqat **ZET / Z** ishlatiladi.
