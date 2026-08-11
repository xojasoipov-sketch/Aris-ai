# ADR-0005 — Design Tokens va Brend Rangi

- **Status:** Qabul qilindi (2026-08-11)
- **Qaror qabul qildi:** Loyiha egasi
- **Yopadi:** Audit topilmasi `F-02`

## Kontekst

Kirish materiallarida ikki xil vizual til bor edi:

| Manba | Palitra |
|---|---|
| `features.md` (prezentatsiya design style) | Grafit `#0B0E14` + **teal/yashil** akцent |
| Dashboard mockuplari (2 ta PNG) | Sof qora + **ko'k/cyan** akцent + oq zarrachalar |

Bitta loyihada ikki brend bo'lishi mumkin emas — biri tanlanishi kerak edi.

## Qaror

**Ko'k/cyan palitra — mockup bo'yicha.** Prezentatsiyaning teal uslubi tark etiladi
(u faqat slaydlar uchun qolgan tarixiy artefakt).

Sabab: mockuplar mahsulotning haqiqiy interfeysi; ular yuqori tafsilotda ishlangan
(dashboard, assistant holatlari, Telegram Mini App) va Bo'lim 10 uchun to'g'ridan-to'g'ri
manba bo'lib xizmat qiladi. Slayd uslubiga moslash uchun ularni qayta ranglash — bekor ish.

## Token'lar (boshlang'ich to'plam)

Bular Bo'lim 10 da aniqlashtiriladi; hozir yagona manba sifatida qayd etiladi.

### Fon va sirtlar
| Token | Qiymat | Ishlatilishi |
|---|---|---|
| `--bg-base` | `#05070D` | Ilova foni (deyarli sof qora) |
| `--bg-surface` | `#0A0E17` | Asosiy panel |
| `--bg-elevated` | `#0F1420` | Ustki karta / modal |
| `--border-subtle` | `#1A2233` | Panel chegarasi |
| `--border-glow` | `rgba(74,158,255,0.25)` | Faol panel chegarasi |

### Akцent
| Token | Qiymat | Ishlatilishi |
|---|---|---|
| `--accent-primary` | `#4A9EFF` | Asosiy ko'k — CTA, faol holat, grafik chiziq |
| `--accent-cyan` | `#38BDF8` | Ikkilamchi — zarrachalar, glow, "thinking" |
| `--accent-glow` | `rgba(56,189,248,0.35)` | Neyro-shar / orb halosi |

### Matn
| Token | Qiymat |
|---|---|
| `--text-primary` | `#E8EDF5` |
| `--text-secondary` | `#8A97AD` |
| `--text-muted` | `#4E5A70` |
| `--text-mono` | `#7BA7D9` (monospace texnik yorliqlar) |

### Semantik holatlar (agent statuslari — mockupdan)
| Token | Qiymat | Holat |
|---|---|---|
| `--state-online` | `#22C55E` | Online |
| `--state-working` | `#F59E0B` | Working |
| `--state-thinking` | `#38BDF8` | Thinking |
| `--state-offline` | `#4E5A70` | Offline / Paused |
| `--state-danger` | `#EF4444` | Xato · yuqori xavfli amal · tasdiq talab |

### Tipografiya
| Rol | Shrift |
|---|---|
| Sarlavha va matn | Inter (yoki system sans) |
| Texnik yorliq / terminal / metrikalar | JetBrains Mono |
| Yorliq uslubi | `UPPERCASE`, `letter-spacing: 0.15em` (mockupdagi kabi) |

### Vizual til
- Sof qora fon, mayda oq nuqtalardan generativ zarrachalar (neyro shar, profil) — `IMG_1701` moodboard'i
- Assistant holat chip'lari: `Thinking…` · `Searching…` · `Agent shaping…` · `Agent listening…` — `IMG_1693`
- Glass panel: `background: rgba(15,20,32,0.6)` + `backdrop-filter: blur(12px)` + nozik chegara
- Radius: panel `16px`, karta `12px`, chip `999px`

## Oqibatlar

- ✅ Bo'lim 10 mockupdan to'g'ridan-to'g'ri quriladi, qayta ranglash yo'q
- ✅ Xavfsizlik holatlari uchun qizil ajratilgan — approval/danger UI aniq ko'rinadi
- ⚠️ Prezentatsiyani (40 slayd) yangilash kerak bo'lsa — alohida ish, mahsulotga ta'sir qilmaydi
- ⚠️ Kontrast tekshiruvi kerak: `--text-muted` qora fonda WCAG AA dan o'tmasligi mumkin →
  Bo'lim 10 da a11y auditi
