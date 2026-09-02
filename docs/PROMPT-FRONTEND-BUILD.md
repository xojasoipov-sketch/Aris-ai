# Prompt — Bo'lim 10 frontend qurish (boshqa model uchun)

> Bu fayl **loyiha spetsifikatsiyasi emas** — u boshqa AI modelga (yoki
> shu modelning kelajakdagi sessiyasiga) berish uchun tayyor **prompt**.
> Repo'da saqlanadi, chunki u ham versiyalanishi kerak (arxitektura
> hujjatlari o'zgarsa, prompt ham yangilanishi kerak).

---

## PROMPT (quyidagini boshqa modelga nusxalab bering)

```
Sen ZET loyihasining frontend muhandisisan. ZET — bir egali shaxsiy AI
operatsion tizim (SaaS emas). Backend to'liq tayyor va ishlaydi
(`apps/core`, Python/FastAPI). Sening vazifang — `apps/web` paketini
noldan qurish: Next.js dashboard + Telegram Mini App.

## 1. MAJBURIY — avval shu fayllarni to'liq o'qi

Boshqa hech narsa qilishdan oldin, repo ichidan quyidagilarni o'qi —
bular yagona haqiqat manbai (single source of truth), taxmin qilma:

1. `docs/adr/ADR-0005-design-tokens.md` — rang/shrift token'lari va
   NEGA teal emas ko'k/cyan tanlangani (F-02 ziddiyati va yechimi)
2. `docs/10-DESIGN-SYSTEM.md` — to'liq komponent inventarizatsiyasi,
   AI assistant holat mashinasi, 12 sahifalik xarita, Telegram Mini
   App spetsifikatsiyasi
3. `docs/11-DEVICE-CONTROL-VIEWS.md` — Devices sahifasi (Kompyuter +
   Telefon tab'lari), approval/kill-switch UI oqimi, mavjud
   backend endpoint'lariga aniq bog'lanish
4. `docs/adr/ADR-0001-tech-stack.md` va `docs/01-VISION-GAP.md` §2.3 —
   frontend tech stack qarori va sababi
5. `docs/02-MASTER-PLAN.md` (Bo'lim 10 qismi) — DoD: "Mockup bilan
   vizual taqqoslash o'tadi; realtime agent statuslari ishlaydi"

## 2. MUHIM CHEKLOVLAR — buzilmasligi kerak

- **Nom: "ZET", "JARVIS" EMAS.** Original mockup'larda "JARVIS" logotipi
  bor edi — bu faqat vizual moodboard, mahsulot nomi emas. Har qanday
  wordmark/logo/matn joyida "ZET" ishlatilsin. (`grep -ri jarvis` repo
  bo'yicha bo'sh qaytishi kerak — bu Z1.0 acceptance criteria.)
- **Original mockup rasm fayllari senga BIRIKTIRILMAGAN.** Ega ilgari
  bitta zip yuklagan edi (`dashboard.png`, `state-machine.png`,
  `status-pills.jpeg`) — ular boshqa (o'tgan) sessiyada tahlil qilinib,
  `docs/10-DESIGN-SYSTEM.md` va `docs/11-DEVICE-CONTROL-VIEWS.md`ga
  to'liq yozma spec sifatida ko'chirilgan. Agar pixel-perfect solishtirish
  kerak bo'lsa (Bo'lim 10 DoD talabi), **egadan rasmlarni qayta so'ra** —
  ularsiz ham ikkala hujjat qurish uchun yetarli, lekin yakuniy vizual
  taqqoslash uchun original kerak bo'ladi.
- **Backend'ga YANGI endpoint qo'shma** — approval (`GET /approvals`,
  `POST /approvals/{id}/approve|reject`) va kill-switch
  (`POST /killswitch/engage|disengage`, `GET /killswitch`) allaqachon
  mavjud. Ulardan foydalan, qayta yozma.
- **Hech qanday sir (`SecretStr`) frontend'ga chiqmasin.** Settings
  sahifasida faqat "sozlangan/sozlanmagan" (bool) ko'rsatiladi.
- **Screenshot UNTRUSTED (A-05).** `desktop.screenshot` natijasi har
  doim "UNTRUSTED" yorlig'i bilan ko'rsatilsin, LLM buyruq sifatida hech
  qachon talqin qilinmasin.
- **EXECUTE darajali amallar (`desktop.type_text/key_press/mouse_click`)
  har doim approval karta orqali o'tadi** — to'g'ridan-to'g'ri
  bajarilmaydi (V-32).
- **Til:** UI matni — o'zbekcha (loyiha egasi o'zbek tilida ishlaydi).
  Kod izohlari ham o'zbekcha — bu repo konvensiyasi (`apps/core/src`ni
  ko'rib chiq, har bir modulda o'zbekcha docstring bor).

## 3. Tech stack (qaror qilingan, muhokama qilinmaydi)

| Qatlam | Tanlov |
|---|---|
| Framework | Next.js 15 (App Router) + React 19 + TypeScript |
| Styling | Tailwind CSS v4 + shadcn/ui |
| Animatsiya | Framer Motion (holat o'tishlari: sleep→listening→thinking) |
| 3D/zarrachalar | react-three-fiber + custom GPU particle shader (neyro shar/profil) |
| Chart | Recharts yoki visx |
| Realtime | SSE (streaming javob) + WebSocket (agent status) |
| Mini App | @telegram-apps/sdk-react |
| Backend client | `openapi-typescript` orqali `apps/core`ning `/openapi.json`
                    sxemasidan tiplangan client generatsiya qil |

## 4. Boshlash tartibi (bosqichma-bosqich, har bosqichda commit)

1. `apps/web/` skeleti — Next.js 15 + TS + Tailwind v4 + shadcn/ui init.
2. `apps/web/tokens.css` — ADR-0005 CSS custom properties'ni aynan
   ko'chir (o'zgartirmasdan).
3. Komponent library — `docs/10-DESIGN-SYSTEM.md` §3 dagi har bir
   komponent (status pill, agent list item, stat card, progress ring,
   camera tile, approval card, ulanish holati badge...) — Storybook
   yoki oddiy `/dev/components` sahifasi orqali izolyatsiyada ko'rsat.
4. AI Assistant holat mashinasi — `docs/10-DESIGN-SYSTEM.md` §3.2 dagi
   Mermaid diagrammani real state machine (masalan XState yoki oddiy
   `useReducer`) sifatida amalga oshir.
5. Dashboard sahifasi — barcha panellarni yig'.
6. Devices sahifasi — `docs/11-DEVICE-CONTROL-VIEWS.md`dagi Kompyuter
   va Telefon tab'lari, approval/kill-switch real API'ga ulangan holda.
7. Telegram Mini App — alohida, yengil bundle, `WebApp.initData`
   autentifikatsiya bilan (R-04: faqat owner_id).
8. **DoD tekshiruvi:** ega bilan birga original mockup'lar (agar u
   qayta ulasa) bilan yonma-yon solishtir.

## 5. Ochiq savollar (senga qoldirilgan qarorlar)

`docs/10-DESIGN-SYSTEM.md` §7 va `docs/11-DEVICE-CONTROL-VIEWS.md` §6
da ro'yxatlangan — ayniqsa:
- Zarracha render: Canvas2D approksimatsiyami yoki to'g'ridan-to'g'ri
  react-three-fiber/WebGL? (Tavsiya: boshidanoq WebGL, chunki stack
  allaqachon shunday tanlangan — ADR-0001 buni tasdiqlaydi.)
- Real-time approval sync (Telegram ↔ Dashboard bir vaqtda yangilanishi)
  — WebSocket kanalini loyihalash senga qoladi.
- Gesture control (SWIPE/PINCH/PALM) — vizual konsepsiyami yoki real
  funksiyami, ega bilan aniqlashtir, taxmin qilma.

## 6. Git workflow

Repo: `xojasoipov-sketch/aris-ai`. Yangi branch'da ishla (masalan
`claude/frontend-bolim10`), har bosqichda mantiqiy commit qil, ADR yozish
zarur bo'lsa (`docs/adr/`) mavjud namunaga ergash.
```

---

## Eslatma (loyiha egasi uchun)

Yuqoridagi kod blokini to'liq nusxalab, boshqa modelga (yangi sessiya,
boshqa vositada) joylashtiring. Agar o'sha model original mockup
rasmlariga ehtiyoj sezsa (pixel-perfect solishtirish uchun), o'sha
zipni (`ZET.zip`) unga ham yuklashingiz kerak bo'ladi — bu sessiyada
tahlil qilingan fayllar boshqa sessiyaga avtomatik ko'chmaydi.
