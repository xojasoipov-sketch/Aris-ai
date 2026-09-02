# ADR-0007 — Local-First Deployment

- **Status:** Qabul qilindi (2026-08-11)
- **Sabab:** Egasi: "hozircha test uchun istalgan joyda, loyiha tugagach kompyuterga to'liq o'tadi"
- **O'zgartiradi:** `ADR-0001` ning deploy qismini
- **Bog'liq:** `ADR-0006` (lokal modellar), `R-04`, `R-05`

## Qaror

ZET **local-first** loyihalanadi: yakuniy uy — egasining kompyuteri, bulut emas.

| Bosqich | Joy | Maqsad |
|---|---|---|
| Bo'lim 1–5 (dev) | Egasining kompyuteri, Docker Desktop | Ishlab chiqish va sinov |
| Bo'lim 6–9 | O'sha joyda + ixtiyoriy arzon VPS (faqat 24/7 jadval uchun) | Biznes integratsiyalari |
| Bo'lim 12 (prod) | **Egasining kompyuteri**, native servis sifatida | Yakuniy holat |

## Bu nimani o'zgartiradi

### 1. Telegram — long polling, webhook emas ⭐

Uy kompyuterida ommaviy IP va TLS sertifikati yo'q, NAT orqasida. Webhook ishlamaydi.
➡️ `aiogram` **long polling** rejimida ishlaydi — ommaviy IP talab qilmaydi,
port ochish shart emas, ngrok/tunnel kerak emas.

Bu **arxitekturaviy qaror**, keyin o'zgartirish qiyin: Bo'lim 9 dagi tashqi
webhook trigger'lari (V-26) uchun alohida yechim kerak bo'ladi
(kichik relay yoki polling-based integratsiya).

### 2. Lokal modellar birinchi darajali (`ADR-0006` T0)

Kompyuterda Ollama ishlashi mumkin → `simple`/`normal` vazifalar **bepul**.
Bu $10 budjetni haqiqiy qiladi.

Talab: kamida **16 GB RAM** (32 GB tavsiya), Apple Silicon yoki diskret GPU.

### 3. Desktop boshqaruvi — masofaviy emas, mahalliy

Vision'da (V-20) kompyuter boshqaruvi masofaviy agent orqali tasavvur qilingan.
Local-first'da ZET **allaqachon o'sha kompyuterda** ishlaydi → tarmoq qatlami,
imzolangan buyruqlar, mTLS kerak emas.

➡️ Bu Bo'lim 8 ni **ancha soddalashtiradi** va `R-05` (qurilma orqali kompromis)
xavfini kamaytiradi — hujum yuzasi tarmoqdan chiqmaydi.

⚠️ Lekin `A-06` (capability token) baribir qoladi: ZET'ning o'zi noto'g'ri
qadam tashlamasligi uchun ruxsatlar shart.

### 4. macOS **va** Windows — ikkalasi

Egasi ikkalasidan ham foydalanadi. Desktop qatlami cross-platform bo'lishi shart.

| Vazifa | Cross-platform yechim |
|---|---|
| Skrinshot | `mss` |
| Klaviatura / sichqoncha | `pynput` |
| Jarayonlar / tizim holati | `psutil` |
| Fayl tizimi | `pathlib` + platformga xos "xavfsiz papkalar" ro'yxati |
| Ilova ishga tushirish | Platform adapteri (`open` / `start` / `xdg-open`) |
| Terminal | `asyncio.create_subprocess_exec` + allowlist |

`PlatformAdapter` protokoli: `MacAdapter`, `WindowsAdapter`, `LinuxAdapter`.
Yadro kodi platformani bilmaydi.

✅ Python tanlagani (`ADR-0001`) bu yerda o'zini oqladi — bitta kod bazasi ikkala OS'da.

### 5. Ma'lumotlar hech qayerga chiqmaydi

Postgres, Obsidian vault, kamera yozuvlari, audit log — hammasi lokal.
Bu vision'ning "private infrastructure · not a public SaaS" (slayd 1) prinsipiga
to'liq mos va maxfiylik jihatidan eng kuchli variant.

### 6. Narxi: 24/7 emas

⚠️ **Eng katta cheklov.** Kompyuter o'chiq bo'lsa:
- Kunlik avtonomiya (08:00 briefing) ishlamaydi
- Telegram buyruqlari javobsiz qoladi
- Kamera hodisalari yozilmaydi

Yechimlar (Bo'lim 12 da tanlanadi):
1. Kompyuter doim yoqiq (uyqu rejimidan uyg'onish jadvali bilan)
2. Arzon VPS'da faqat "yengil qatlam" (Telegram qabul qiluvchi + jadval),
   og'ir ish kompyuter yoqilganda bajariladi (navbat orqali)
3. Eski noutbuk / mini-PC ni doimiy ZET serveri qilish ⭐ tavsiya

## Oqibatlar

- ✅ Server xarajati $0
- ✅ Lokal modellar → LLM xarajati keskin tushadi
- ✅ Maxfiylik maksimal
- ✅ Bo'lim 8 soddalashadi (masofaviy protokol yo'q)
- ⚠️ 24/7 avtonomiya uchun alohida qaror kerak (Bo'lim 12)
- ⚠️ Backup endi egasining mas'uliyati → `RUNBOOK.md` da majburiy bo'lim
- ⚠️ Ollama uchun apparat talabi (16+ GB RAM)
