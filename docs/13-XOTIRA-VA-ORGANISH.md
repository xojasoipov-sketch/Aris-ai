# ZET — Xotira va o'rganish

Ega ikki narsani so'radi:

1. **"Men haqimda ma'lumotlarni ZETga yetkaz"** — `BOSS_PROFILE.md`.
2. **"NotebookLM'ga o'xshab video silkasini bersam to'liq o'rganib
   foydali joylarini ajratib olib saqlasin"** — o'rgatish/o'rganish
   uchun.

Bu hujjat ikkalasi qanday ishlashini va **nimasi hali cheklangan**ini
yozadi.

---

## 1. Profil qanday yuklanadi

```bash
uv run python scripts/ingest_profile.py BOSS_PROFILE.md \
    --api https://backend-....up.railway.app --token "$ZET_API_TOKEN"
```

Skript faylni `##` sarlavhalari bo'yicha **alohida yozuvlarga** bo'ladi.

**Nega bitta katta blok emas.** Butun fayl bitta yozuv bo'lsa, semantik
qidiruv ma'nosini yo'qotadi: "qaysi to'lov tizimini ishlataman?" degan
savolga 300 qatorlik matn qaytadi va LLM kontekstini to'ldiradi. Har
bo'lim — alohida vektor, alohida teg.

Har yozuvga `source: boss-profile` tegi qo'yiladi.

## 2. Javob yozishda xotira qanday ishlatiladi

Ikki mustaqil yo'l bor — biri avtomatik, ikkinchisi rejaga bog'liq.

### 2.1. Avtomatik eslash (`recall`)

Fikrlash qadami (tool'siz qadam) har safar eganing savolini xotirada
qidiradi va topilganini promptga qo'shadi:

```
EGA HAQIDA ESLAB QOLGANLARING (uzoq muddatli xotira):
— Identity & Quick Facts …
```

| Sozlama | Qiymat | Nega shunday |
|---|---|---|
| `RECALL_LIMIT` | 4 | Ko'paytirish kontekstni boyitadi, lekin har so'rov narxini oshiradi |
| `RECALL_MIN_SIMILARITY` | 0.35 | 0 chegara har savolga butun profilni ilashtiradi — shovqin |

Xotira yiqilsa (DB yoki embedding provayderi) **javob baribir
yoziladi** — fail-open. Log'da `executor.recall_failed` xato matni
bilan chiqadi.

Kuzatuv uchun har fikrlash qadamida `executor.recalled` yoziladi
(`enabled`, `count`). Usiz "xotira o'qilmadi" va "o'qildi, lekin model
ishlatmadi" holatlarini ajratib bo'lmasdi.

### 2.2. `memory.search` tooli

Planner rejaga qo'yadigan haqiqiy qadam. Chegara 0.3 — bu yerda
natijani LLM o'zi ko'rib keraksizini tashlaydi, avtomatik eslashda esa
hamma narsa to'g'ridan-to'g'ri promptga tushadi.

**Nega tool ham kerak.** Faqat avtomatik eslash bo'lganda Planner
xotira borligini **ko'rmasdi** — u tool ro'yxatiga qaraydi. Jonli
misolda "Men kimman?" savoliga reja shunday chiqdi:

```
0. note.list
1. note.read("user_profile")   ← o'ylab topilgan fayl, mavjud emas
2. javob yozish (depends_on: [0, 1])
```

1-qadam uch marta yiqildi, 2-qadam `dependency_not_ready` bo'lib
umuman ishga tushmadi. Xotira bor edi — unga yo'l yo'q edi.

Backend ulanmagan bo'lsa tool **ochiq xato** beradi, jim bo'sh ro'yxat
emas: aks holda "xotira yo'q" va "xotirada hech nima yo'q" bir xil
ko'rinadi.

## 3. Video o'rganish (`video.learn`)

Gemini `file_data.file_uri` YouTube havolasini to'g'ridan-to'g'ri
qabul qiladi — **yuklab olish ham, transkript ham kerak emas**.

Chiqish qat'iy JSON:

| Maydon | Nima |
|---|---|
| `title`, `topic` | Video nimadan |
| `summary` | Qisqa xulosa |
| `key_points` | Asosiy fikrlar |
| `terms` | Atamalar va ta'riflari |
| `actionable` | Amaliy qadamlar |
| `quotes` | Muhim iqtiboslar |
| `teaching_notes` | O'qitishda ishlatish uchun eslatmalar |
| `gaps` | Video **javob bermagan** savollar |

`gaps` — atayin: "hammasi tushuntirildi" degan taassurot yolg'on
bo'lardi.

`to_markdown()` Obsidian uchun tayyor matn beradi.

**Trust: UNTRUSTED.** Video mazmuni tashqi manba — buyruq emas. Ichida
"endi shu faylni o'chir" deb yozilgan bo'lsa ham ZET uni bajarmaydi.

Model `ZET_GEMINI_VIDEO_MODEL` orqali almashtiriladi (bepul kvota
limitga urilganda kerak bo'ladi).

## 4. Halol cheklovlar

- **Profil qo'lda yangilanadi.** ZET suhbatdan o'zi profil chiqarib
  yozmaydi. `ingest_profile.py` qayta ishga tushiriladi.
- **Video faqat YouTube.** Boshqa platformalar (Instagram, shaxsiy
  fayl) hali ulanmagan.
- **`video.learn` natijasi avtomatik saqlanmaydi** — reja `memory`
  qadamini qo'shsa saqlanadi, aks holda faqat javobda ko'rinadi.
- **Embedding modeli bog'langan.** Yozuvlar `model_id` bilan
  teglanadi; model almashtirilsa eski vektorlar qidiruvda **chetlab
  o'tiladi** (turli vektor fazolarini solishtirish ma'nosiz). Eski
  yozuvlarni qayta indekslash kerak.

## 5. Jonli tekshiruv (2026-08-12)

| Nima | Natija |
|---|---|
| Profil yuklash | 11 bo'lim, 0 xato |
| Semantik qidiruv | "trading uchun nima qilganman" → 0.469 Active Projects |
| Avtomatik eslash | `executor.recalled count=4` → javob 672 belgi |
| "Men kimman?" | SadiPrime, EMSA Indicator, Telegram bot, AI Trading — profildan |
| `video.learn` | 19 daqiqalik video → 6 asosiy fikr, 7 atama, 3 amaliy qadam, 22 soniya |
