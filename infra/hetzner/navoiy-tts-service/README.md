# Navoiy TTS inference mikroservisi (Hetzner GPU)

## OCHIQ E'LON QILINGAN HOLAT — bu qism TO'LIQ SINALMAGAN

Bu servis **CosyVoice2/Navoiy TTS'ni haqiqiy GPU'da ishga tushirmasdan
yozilgan** — bu sandbox'da GPU yo'q, shuning uchun quyidagilar
TASDIQLANMAGAN:

- `aisha-org/navoiy-tts` checkpoint'ining (`emotion_600h_joint.pt`,
  1.88 GiB) aniq `--reference`/`--emotion` qiymatlari — repo fayl
  ro'yxatini (reference audio nomlarini) haqiqiy yuklab olib
  tekshirmaguningizcha bu qiymatlar **taxminiy**.
- Server kodi (`server.py`) ishga tushishi, xotira/vaqt sarfi.
- Chiqish audio sifati.

Bu — WebSearch/WebFetch orqali tekshirilgan HAQIQIY topilmalar asosida
yozilgan (manbalar pastda), lekin GPU'da birinchi marta ishga
tushirishda **siz** tekshirishingiz va kerak bo'lsa sozlashingiz kerak
bo'ladi. Nima ishlamasa — bu yerda yozilgan taxminlardan biri
noto'g'ri chiqqani degani, "yashirin bug" emas.

## Tasdiqlangan faktlar (WebSearch/WebFetch, 2026-08-17)

- Asos model: `FunAudioLLM/CosyVoice2-0.5B`
- CosyVoice repo commit: `074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc`
- Checkpoint: `aisha-org/navoiy-tts/emotion_600h_joint.pt` (1.88 GiB)
- **Litsenziya: Apache-2.0** (tijoratga ham ochiq — MMS-TTS'dagi
  CC-BY-NC-4.0 muammosi BU YERDA YO'Q)
- Chiqish: 24 kHz audio, CUDA talab qiladi
- Rasmiy ishga tushirish: `navoiy-tts/inference.py --cosyvoice-dir
  --base-model-dir --checkpoint --reference --text --emotion --output`

Manba: aisha.group blog posti, `aisha-org/navoiy-tts` HuggingFace model
kartasi, WebSearch natijalari (aniq URL'lar frontend chatda ko'rsatilgan).

## Arxitektura

```
ZET backend (CPU, Railway/Hetzner)
    │  NavoiyTTS (zet/voice/navoiy_tts.py) — HTTP client
    ▼
navoiy-tts-service (GPU Hetzner box) — bu papka
    │  POST /synthesize {"text": "..."}  →  audio/ogg baytlar
    ▼
navoiy-tts/inference.py (subprocess) — aisha-org'ning O'Z skripti
    │  --text ... --reference ... --emotion ... --output /tmp/out.wav
    ▼
CosyVoice2 (GPU inference)
```

Nega subprocess (Python API'ni to'g'ridan-to'g'ri chaqirish emas): aisha-org
checkpoint'ining CosyVoice2 ichiga aniq QANDAY yuklanishi (to'liq
state_dict o'rniga, LoRA, decoder-only va h.k.) hujjatlashtirilmagan —
bu holatni TAXMIN qilib noto'g'ri Python integratsiya yozish xato audio
yoki portlashga olib kelishi mumkin. Ularning O'Z `inference.py`
skriptini subprocess sifatida chaqirish xavfsizroq: to'g'rilikni ular
maintain qiladi, biz faqat kirish/chiqishni bog'laymiz.

## Sozlash (operator qadamlari — SIZ bajarasiz)

1. **GPU server tanlash.** Hetzner Cloud'da hozircha standart GPU Cloud
   instance yo'q (2026-08 holati aniq emas — Hetzner Console'dan
   tekshiring) — ehtimol dedicated GPU server (GEX44/GEX130 turkumi)
   kerak bo'ladi. Muqobil: RunPod/Vast.ai'da faqat shu servis uchun
   alohida GPU instance (asosiy backend Hetzner'da qolaveradi — ular
   faqat HTTP orqali gaplashadi, bir joyda bo'lishi shart emas).

2. **Repo tayyorlash:**
   ```bash
   git clone https://github.com/FunAudioLLM/CosyVoice.git
   cd CosyVoice && git checkout 074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc
   git submodule update --init --recursive
   huggingface-cli download FunAudioLLM/CosyVoice2-0.5B --local-dir pretrained_models/CosyVoice2-0.5B
   huggingface-cli download aisha-org/navoiy-tts --local-dir /opt/navoiy-tts
   ```

3. **MUHIM — bu qadamni SIZ bajarishingiz kerak:** `/opt/navoiy-tts`
   ichidagi fayl ro'yxatini ko'ring (`ls /opt/navoiy-tts`) — reference
   audio fayllari va emotion nomlari qanday ekanini aniqlang, keyin
   `.env`dagi `NAVOIY_REFERENCE_PATH`/`NAVOIY_DEFAULT_EMOTION`ni shunga
   qarab to'g'rilang (`docker-compose.gpu.yml`dagi default qiymatlar
   FAQAT TAXMIN, tekshirmasdan ishlatilmasin).

4. Qurish va ishga tushirish:
   ```bash
   docker compose -f docker-compose.gpu.yml up -d --build
   curl -X POST http://localhost:8100/synthesize -d '{"text":"Salom"}' \
       -H 'Content-Type: application/json' -o test.ogg
   ```

5. ZET backend `.env`ga qo'shing:
   ```bash
   ZET_NAVOIY_TTS_BASE_URL=http://<GPU_SERVER_IP>:8100
   ```

## Xarajat (taxminiy, siz tanlagan provayderga qarab)

- Hetzner dedicated GPU (GEX44 turkumi, RTX 4000 SFF Ada) — taxminan
  **€200-250/oy** (doimiy ishlaydi, 24/7).
- RunPod/Vast.ai on-demand (faqat kerak bo'lganda ishga tushirilsa) —
  ancha arzonroq (~$0.2-0.4/soat), lekin sovuq-start kechikishi
  (model yuklash, 30s-2min) har safar bo'ladi, agar konteyner doimiy
  ishlab turmasa.

Bu raqamlar 2026-08 holatiga taxminiy — buyurtma qilishdan oldin
provayderning joriy narxini o'zingiz tekshiring.
