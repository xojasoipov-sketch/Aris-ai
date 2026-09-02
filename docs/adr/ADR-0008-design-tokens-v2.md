# ADR-0008 — Design Tokens v2 (ega master prompti)

- **Status:** Qabul qilindi (2026-08-12)
- **Qaror qabul qildi:** Loyiha egasi
- **Bekor qiladi:** `ADR-0005` (design tokens v1)

## Kontekst

Bo'lim 10 birinchi iteratsiyasi ADR-0005 token'lari bilan qurildi va ega
ko'rib chiqdi. Ega o'z mockuplarini piksel-tahlil qilingan **yangi master
dizayn tizimi** bilan qaytardi ("Men aytgan dizayn emas — qayta qurasan").
Asosiy farqlar shunchaki rang emas — uslub falsafasi:

| Jihat | v1 (ADR-0005) | v2 (bu ADR) |
|---|---|---|
| Fon | `#05070D` | `#050608` (ko'k tint, hech qachon sof qora) |
| Akцent | `#4A9EFF` / cyan `#38BDF8` | `#4C8DFF` / glow `#7DD3FC` |
| Karta | Glass (blur) hamma joyda | **Hairline chegara + inset highlight; blur FAQAT floating/modal** |
| Sidebar faol | Pill fon | **border-left akцent** |
| Shrift | Inter + JetBrains Mono | **Geist Sans + Geist Mono** (self-host) |
| Ikon | qo'lda SVG | **lucide-react**, stroke 1.5 |
| Animatsiya | framer-motion | **motion/react**, bounce taqiqlangan |
| Markaziy vizual | zarracha shar (4 holat) | **NeuroOrb 6 holat**, speaking'da yuz-morph |

To'liq tizim: `apps/web/CLAUDE.md` (yagona amaldagi nusxa — bu ADR faqat
qarorni va sabablarni qayd etadi, token ro'yxatini takrorlamaydi).

## Qaror

Ega bergan master tizim to'liq qabul qilinadi. `apps/web` shu tizim bo'yicha
qayta quriladi (fazalab). Mahsulot nomi **ZET** bo'lib qoladi — master
promptdagi "JARVIS" so'zi moodboard nomi, Z1.0 acceptance criteria kuchda
(`grep -ri jarvis` kod bo'ylab bo'sh).

## Oqibatlar

- ✅ "Multfilm ko'rinish" xavfi yopiladi: qat'iy taqiqlar ro'yxati (purple
  gradient, box-shadow yulduz, bounce easing, blur-hamma-joyda) code review
  mezoniga aylanadi
- ✅ Bitta signature komponent (NeuroOrb) — 5 xil animatsiya o'rniga bitta
  shader parametrlanadi
- ⚠️ ADR-0005 asosidagi birinchi iteratsiya (Z33.1–Z33.2) qayta ishlanadi
- ⚠️ `docs/10-DESIGN-SYSTEM.md` §1 token jadvali endi tarixiy — komponent
  inventarizatsiyasi va sahifa xaritasi (§3–5) kuchda qoladi
