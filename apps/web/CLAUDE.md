# ZET web — MASTER DIZAYN TIZIMI (ega tomonidan, 2026-08-12)

> Bu fayl — `apps/web` uchun OLIY qonun. Har bir yangi ekran/komponent AYNAN
> shunga rioya qiladi. Manba: ega yuborgan JARVIS-konsept mockuplari (5 rasm)
> asosidagi master prompt. Mahsulot nomi **ZET** (repo Z1.0 qoidasi: "JARVIS"
> so'zi kodda ishlatilmaydi — u faqat moodboard nomi edi).
> ADR-0008 shu tizimni rasmiylashtiradi (ADR-0005 eskirdi).

## STACK
- Next.js 15 (App Router) + TypeScript (strict)
- Tailwind CSS v4
- Motion (`motion/react`) — barcha animatsiyalar shu bilan (framer-motion EMAS)
- 3D/particle: @react-three/fiber (+ kerak bo'lsa drei) + custom GLSL shader
- Grafiklar: custom SVG (sparkline/radial); murakkab chart kerak bo'lsa Recharts
- Ikonkalar: lucide-react, strokeWidth global 1.5, bitta hajm (18–20px)
- Fontlar: next/font orqali self-host (`geist` paketi) — Google Fonts <link> YO'Q

## RANG TOKENLARI (rasmlardan piksel-tahlil)
```
--bg-base:        #050608   (asosiy fon — deyarli qora, ozgina ko'k tint)
--bg-elevated:    #0b0e14   (panel/card foni)
--surface-hover:  #14161c
--border-hairline: rgba(255,255,255,0.08)  (1px, hech qachon qalinroq emas)
--border-active:   rgba(90,160,255,0.45)
--text-primary:    #F2F4F8
--text-secondary:  #8A8F9C
--text-muted:      #4B4F58
--accent-blue:     #4C8DFF   (tugma, faol holat, sfera nuri)
--accent-glow:     #7DD3FC   (sfera markaziy "issiq" nuqtasi)
--status-online:   #22C55E
--status-working:  #F59E0B
--status-thinking: #F59E0B   (working bilan bir xil rang, animatsiya boshqa)
--status-offline:  #4B4F58
--status-alert:    #EF4444
```
Fon HECH QACHON toza #000000 emas — doim ozgina ko'k-qora tint.

## TIPOGRAFIYA
- UI: Geist Sans (o'rtacha weight)
- Data/raqamlar (CPU%, uptime, tarmoq): Geist Mono + tabular-nums —
  yangilanishda "sakramaydi"
- Eyebrow label ("SYSTEM STATUS", "ACTIVE AGENTS"): 10–11px, UPPERCASE,
  letter-spacing 0.08–0.12em, --text-muted
- H1/H2 oddiy, og'ir emas — texnik dashboard, jurnal emas

## KARTA/PANEL USLUBI
- border-radius: 14–16px (pill/chip/tugma — 999px)
- border: 1px solid var(--border-hairline) — asosiy chegara usuli, og'ir shadow YO'Q
- Ichki yorug'lik: yuqori qirrada past-opacity oq inset chiziq
- **backdrop-blur FAQAT floating widget va modal'larda** — oddiy kartalarda EMAS
- Hover: border --border-active + juda yengil scale (1.01), sakramaydi

## HARAKAT (Motion)
- Kirish: stagger, pastdan 8–12px + opacity 0→1, 300–400ms, ease-out
- Sfera: idle'da ~20–30s/aylanish, hech qachon to'xtamaydi (offline'dan tashqari)
- Status almashinuvi: crossfade / layoutId morph
- Hover/active: 150–200ms, spring(stiffness 300, damping 30)
- prefers-reduced-motion: ambient animatsiyalar statik holatga

## SIGNATURE: <NeuroOrb /> (bitta komponent, props bilan holat)
state: "idle" | "listening" | "thinking" | "speaking" | "searching" | "offline"
- idle: silliq aylanuvchi sfera (Fibonacci taqsimot)
- listening: mikrofon amplitudasiga to'lqin deformatsiyasi (uLevel uniform)
- thinking: nuqtalar ichki pulsatsiya, noise displacement, zichlashish
- speaking: sfera → profil-yuz morph (vertex interpolation, CPU target array)
- searching: nuqtalar radial tarqalib qaytadi (scatter loop)
- offline: aylanish to'xtaydi, nurlanish 40% xira
Screenspace 2D nuqta EMAS — haqiqiy 3D nuqta-bulut, R3F + GLSL.

## <AgentStatusChip />
Pill: chapda 28–32px mini-NeuroOrb (BITTA shader, boshqa seed/parametr —
5 alohida animatsiya yozilmaydi) + matn: "Thinking…", "Solving…", "Working…",
"Listening…", "Agent searching…" (UI matni o'zbekcha bo'lishi mumkin).

## QAT'IY TAQIQLAR (chiqsa — reject)
- Purple/pink AI-gradient fon
- CSS box-shadow "yulduz" effekti (flat, 3D emas)
- Bootstrap-uslub qalin shadow
- Interfeys ichida emoji (faqat matn/ikonka)
- Bounce/elastic easing
- Hardcoded px qiymatlar — hammasi token/CSS var orqali
- Oddiy kartada backdrop-blur

## FAZALAR (ketma-ket, har biri alohida commit)
1. Skelet + Dashboard (sidebar, pastki fixed status-bar, 400–500px orb,
   System Status radial+sparkline, Active Agents 5, Quick Actions)
2. /ai-chat (orb holat tsikli, ovoz to'lqini — Web Audio AnalyserNode tuzilma,
   model/kontekst selektor, AgentStatusChip demo bloki)
3. /agents /projects /tasks /calendar /messages (mobilda bottom-tab-bar)
4. /analytics /devices /camera /terminal /settings
5. Floating widget + bildirishnoma kartasi + Telegram Mini App (/tg,
   WebApp SDK theme_params)

## BOSHQA QOIDALAR (repo'dan meros)
- UI matni va kod izohlari — o'zbekcha
- Sirlar (SecretStr) frontend'ga chiqmaydi
- EXECUTE amallar faqat approval orqali (V-32); screenshot UNTRUSTED (A-05)
- Backend'ga yangi endpoint qo'shilmaydi
- Tovushlar: lib/sound.ts (WebAudio sintez) — holat o'tishlariga ulangan holda qoladi
