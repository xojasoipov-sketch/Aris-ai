# ZET

**Shaxsiy AI Operatsion Tizimi** — bitta egaga tegishli, ommaviy SaaS emas.

> An'anaviy AI: `Foydalanuvchi → Savol → Javob`
> **ZET: `Foydalanuvchi → Buyruq → Reja → Harakat → Tekshirish → Natija`**

Hozirgi holat: **P0 — Repository Audit yakunlandi.** Kod hali yozilmagan.

## Hujjatlar

| Hujjat | Mazmuni |
|---|---|
| [`docs/00-AUDIT.md`](docs/00-AUDIT.md) | Kirish materiallari inventarizatsiyasi, vision'dan chiqarilgan 45 ta talab (`V-01…V-45`), repository auditi, 8 ta topilma |
| [`docs/01-VISION-GAP.md`](docs/01-VISION-GAP.md) | Gap matritsasi, tech stack qarorlari, 8 ta arxitekturaviy tuzatish (`A-01…A-08`), 12 ta xavf (`R-01…R-12`) |
| [`docs/02-MASTER-PLAN.md`](docs/02-MASTER-PLAN.md) | 12 bo'lim / 18 faza, har birining natijasi va DoD'i |
| [`docs/03-SECTION-1.md`](docs/03-SECTION-1.md) | **Bo'lim 1** — 18 ta task, har biri 7 maydon bilan (nima, fayllar, dependency, test, acceptance, risk, vaqt) |
| [`docs/04-CONSTRAINTS.md`](docs/04-CONSTRAINTS.md) | Egasining cheklovlari (`C-01…C-07`), qayta ko'rilgan ketma-ketlik, **MVP nuqtasi**, Lean Bo'lim 1 |

## Qabul qilingan qarorlar (ADR)

| ADR | Qaror |
|---|---|
| [`0001`](docs/adr/ADR-0001-tech-stack.md) | Tech stack: **Python 3.12 + FastAPI + Postgres/pgvector + Redis** |
| [`0005`](docs/adr/ADR-0005-design-tokens.md) | Brend: **ko'k/cyan palitra** (mockup bo'yicha), design token'lar |
| [`0006`](docs/adr/ADR-0006-model-strategy-and-budget.md) | Model strategiyasi: **4 tier** (Lokal → Free → Arzon → Kuchli) + qattiq budjet chegaralari |
| [`0007`](docs/adr/ADR-0007-deployment-local-first.md) | Deployment: **local-first** (egasining kompyuteri), Telegram long polling, cross-platform desktop |

## MVP yo'li

**Bo'lim 1 → 2 → 3 → 4 (Telegram)** ≈ 8–9 hafta → telefondan to'liq boshqariladigan ZET.

## Rivojlanish prinsipi

Hammasini birdan qurma. Har bir bo'lim oxirida 4 ta artefakt majburiy:
**Implementation · Tests · Verification · Documentation.**
