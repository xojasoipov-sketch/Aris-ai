# ZET — Hetzner (o'z serveringizda) deploy

Nega bu kerak: Railway'ning bepul-qatlam cheklovlari (LLM rate limit,
Ollama yo'qligi, volume qo'lda sozlash) bu loyihada bir necha marta
ZET'ni to'xtatib qo'ydi (`docs/13-XOTIRA-VA-ORGANISH.md`,
`docs/12-AUTONOMY-GAP.md`ga qarang). O'z serveringizda:

- **Lokal Ollama** — embedding va oddiy javoblar bulut kvotasiga bog'liq emas
- **To'liq CPU/RAM** — Railway'ning resurs chegarasi yo'q
- **Doimiy Docker volume'lar** — qo'lda panel sozlash shart emas
- **Xohlagan modelni ishga tushirish**

ZET'ning ichki xavfsizlik arxitekturasi (killswitch, ruxsat darajalari,
tasdiqlash darvozalari, budjet chegaralari) **o'zgarmaydi** — bular
platformaga bog'liq emas, ZET kodining o'zida.

## Talablar

- Hetzner (yoki istalgan) VPS: Ubuntu 22.04/24.04, kamida **4 GB RAM**
  (Ollama + Postgres + backend + web birga). `qwen3:8b` uchun 8 GB
  tavsiya etiladi.
- SSH kirish (parol emas, **SSH key** tavsiya etiladi)
- (Ixtiyoriy) domen — HTTPS uchun. Bo'lmasa IP:port orqali ham ishlaydi.

## 1-qadam — SSH key qo'shish

Hetzner Cloud Console → Security → SSH Keys → server yaratishda yoki
mavjud serverga:

```bash
# O'z kompyuteringizda (yoki shu public key'ni Hetzner panelga qo'shing):
ssh-keygen -t ed25519 -f ~/.ssh/hetzner_zet -C "zet"
cat ~/.ssh/hetzner_zet.pub   # shu qatorni Hetzner panelga qo'shing
```

## 2-qadam — Serverga ulanish va bootstrap

```bash
ssh -i ~/.ssh/hetzner_zet root@<SERVER_IP>

curl -fsSL https://raw.githubusercontent.com/xojasoipov-sketch/aris-ai/claude/zetproject-audit-plan-p9lysv/infra/hetzner/setup.sh | bash
```

Skript birinchi ishga tushishda **to'xtaydi** va sizdan ikkita faylni
to'ldirishni so'raydi (`.env`, `.env.web`) — chunki sirlar avtomatik
yaratilmaydi, siz to'ldirasiz.

## 3-qadam — `.env` to'ldirish (serverda, TO'G'RIDAN-TO'G'RI)

```bash
nano /opt/zet/infra/hetzner/.env
```

Kamida ikkitasi **majburiy**:

```bash
POSTGRES_PASSWORD=<kuchli-tasodifiy-parol>
ZET_API_TOKEN=<kuchli-tasodifiy-token>
```

Tasodifiy qiymat yaratish:

```bash
openssl rand -hex 32
```

Boshqa maydonlar (`ZET_TELEGRAM_BOT_TOKEN`, `ZET_GOOGLE_API_KEY`,
h.k.) — ixtiyoriy, mavjud xizmatlarga qarab to'ldiring.

**MUHIM: bu tokenlarni menga (ZET AI agentiga) yoki chatga hech qachon
yubormang.** Faqat serverdagi faylga, to'g'ridan-to'g'ri.

So'ng:

```bash
nano /opt/zet/infra/hetzner/.env.web
# ZET_API_TOKEN — .env dagi bilan AYNAN bir xil qiymat
```

(Ixtiyoriy) domen bo'lsa, `.env` faylining oxiriga:

```bash
ZET_DOMAIN=zet.example.com
ZET_API_DOMAIN=api.zet.example.com
```

DNS'da ikkala domen ham server IP'siga A-record bilan yo'naltirilgan
bo'lishi kerak — aks holda Caddy TLS sertifikat ololmaydi.

## 4-qadam — qayta ishga tushirish

```bash
sudo bash /opt/zet/infra/hetzner/setup.sh
```

Bu safar Postgres/Redis/Ollama ko'tariladi, Ollama modellari
(`qwen3:8b`, `bge-m3`) tortib olinadi (~5-10 daqiqa, internetga
bog'liq), so'ng backend + web + Caddy quriladi va ishga tushadi.

## 5-qadam — tekshirish

```bash
docker compose -f /opt/zet/infra/hetzner/docker-compose.prod.yml ps
docker compose -f /opt/zet/infra/hetzner/docker-compose.prod.yml logs -f backend
```

Domen bilan: `https://api.zet.example.com/api/v1/health` → `{"status":"ok"}`
Domensiz: `http://<SERVER_IP>:8000/api/v1/health`

## Yangilash (keyingi deploylar)

```bash
cd /opt/zet && git pull origin claude/zetproject-audit-plan-p9lysv
sudo bash infra/hetzner/setup.sh
```

`.env` fayllar qayta yaratilmaydi (ustiga yozilmaydi) — faqat kod
yangilanadi va konteynerlar qayta quriladi.

## Ma'lumotlar bazasi migratsiyasi (Railway'dan)

Agar Railway'dagi mavjud ma'lumotlarni (xotira, profil, suhbat
tarixi) ko'chirmoqchi bo'lsangiz:

```bash
# 1. Railway'dan dump oling (Railway CLI yoki panel orqali DATABASE_URL bilan)
pg_dump "$RAILWAY_DATABASE_URL" --no-owner --no-acl > zet_backup.sql

# 2. Faylni serverga ko'chiring
scp -i ~/.ssh/hetzner_zet zet_backup.sql root@<SERVER_IP>:/opt/zet/

# 3. Serverda — yangi Postgres'ga import
ssh -i ~/.ssh/hetzner_zet root@<SERVER_IP>
docker exec -i zet-postgres psql -U zet -d zet < /opt/zet/zet_backup.sql
```

## Obsidian vault

ZET'ning `note.write`/`note.read`/`note.list` tool'lari `.env`dagi
`ZET_VAULT_DIR` (default: `/data/vault`) papkasida ishlaydi — bu
`vault_data` nomlangan Docker volume'ga bog'langan, shuning uchun
`update.sh` bilan konteyner qayta qurilganda yozuvlar **yo'qolmaydi**
(Railway'da bu volume yo'q edi — ephemeral konteyner har redeploy'da
vault'ni tozalab yuborardi).

Bu — ZET'ning O'ZI yozadigan/o'qiydigan papka. Haqiqiy Obsidian dastur
(desktop/mobil ilova)ni shu papkaga ULASH alohida qadam va uch yo'l bor
(hajmi/tez-tezligiga qarab tanlang):

- **Sync papka** — server papkasini Syncthing/Google Drive/iCloud kabi
  vositalar bilan o'z kompyuteringizga sinxronlab, Obsidian'ni o'sha
  mahalliy nusxaga ochasiz.
- **Git vault** — `vault_data`ni alohida git repo qilib, Obsidian Git
  plugin bilan pull/push qilasiz (versiyalangan tarix bilan).
- **Obsidian Local REST API** — o'z kompyuteringizda Obsidian ochiq
  turadi, ZET tarmoq orqali (tunnel/ngrok) unga to'g'ridan-to'g'ri
  ulanadi (real vaqtli, lekin kompyuter doim yoniq bo'lishi shart).

Railway'dan mavjud vault ma'lumotini ko'chirish (agar bo'lsa):

```bash
# Railway konteyneridan (agar hali ishlab tursa):
docker cp <railway-konteyner>:/app/vault ./vault-eski
# Serverga:
scp -i ~/.ssh/hetzner_zet -r ./vault-eski root@<SERVER_IP>:/tmp/
ssh -i ~/.ssh/hetzner_zet root@<SERVER_IP>
docker cp /tmp/vault-eski/. zet-backend:/data/vault/
```

## Ikkalasini parallel ishlatish

Hetzner sinovdan o'tguncha Railway'ni **o'chirish shart emas** —
ikkalasi bir vaqtda ishlashi mumkin (turli domen/Telegram bot bilan,
yoki bittasi sinov, ikkinchisi ishlab turgan holda). Telegram bot
tokeni faqat bittasida faol bo'lishi kerak — ikkala tomon bir xil
tokenni ishlatsa `getUpdates` polling'i to'qnashadi.

## Backup va restore

Kunlik Postgres nusxasi `zet-backup` konteyneri orqali AVTOMATIK
yaratiladi (GAP_ANALYSIS.md HR-02):

- **Jadval:** har kuni 03:15 UTC (Toshkent bo'yicha 08:15).
- **Format:** `zet-YYYY-MM-DD_HHMM.sql.gz` (plain SQL, gzip 9).
- **Joy:** host'da `/var/backups/zet/` — konteyner tushib qolsa ham qoladi.
- **Retention:** 14 kun (`BACKUP_RETENTION_DAYS` env orqali sozlanadi).
- **Ilk nusxa:** konteyner birinchi startida darhol yaratiladi
  (birinchi cron faqat 03:15'da otilar edi).

### Qo'lda backup ishga tushirish

```bash
docker exec zet-backup /backup.sh
```

### Restore (ma'lumotni tiklash)

**DIQQAT:** joriy jadval ma'lumotini o'chirib, backup versiyasini
o'rniga yozadi. Avval joriy holatning nusxasini oling.

```bash
# 1. Joriy holatdan xavfsizlik nusxasi
docker exec zet-backup /backup.sh

# 2. Tiklamoqchi bo'lgan nusxani tanlang
ls -lh /var/backups/zet/

# 3. Tiklash
gunzip -c /var/backups/zet/zet-2026-08-13_0315.sql.gz | \
    docker exec -i zet-postgres psql -U zet -d zet

# 4. Backend qayta ishga tushirish (jadval o'zgargani uchun)
docker compose -f /opt/zet/infra/hetzner/docker-compose.prod.yml restart backend
```

### Backup'ni tashqi joyga ko'chirish (tavsiya)

Serverning o'zi buzilsa `/var/backups/zet` ham yo'qoladi. Muhim
o'rnatishlar uchun nusxalarni tashqi joyga muntazam ko'chirib turing
(masalan `restic → S3/B2` yoki oddiy `rsync`), masalan cron orqali:

```
30 3 * * * rsync -a /var/backups/zet/ user@backup-host:/backups/zet/
```
