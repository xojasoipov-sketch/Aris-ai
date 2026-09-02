#!/bin/sh
# ZET — Postgres kunlik backup (GAP_ANALYSIS.md HR-02).
#
# `backup` konteyneri ichida ishlaydi (Alpine+postgres-client). Har kuni
# 03:15 UTC'da (server jimjit paytida) `pg_dump | gzip` → /backups
# katalogiga yozadi va 14 kundan eski nusxalarni tozalaydi.
#
# Restore (host'da yoki backup konteynerida):
#   gunzip -c /backups/zet-YYYY-MM-DD.sql.gz | \
#     docker exec -i zet-postgres psql -U zet -d zet
#
# XAVFSIZLIK: parol muhit o'zgaruvchisi (`POSTGRES_PASSWORD`) orqali
# uzatiladi — hech qachon logga chiqarilmaydi. `/backups` host volume'da
# saqlanadi (`update.sh` uni /var/backups/zet ga bog'laydi).
set -eu

STAMP=$(date -u +%Y-%m-%d_%H%M)
OUT="/backups/zet-${STAMP}.sql.gz"
RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-14}

# pg_dump'ni `-Fc` (custom format) qilmaymiz — oddiy SQL o'qishi va
# tiklashi osonroq, hajmi juda katta emas (bir egali tizim).
export PGPASSWORD="${POSTGRES_PASSWORD}"

echo "[$(date -u +%FT%TZ)] backup start → $OUT"
pg_dump -h postgres -U zet -d zet --no-owner --clean --if-exists \
    | gzip -9 > "$OUT.tmp"
mv "$OUT.tmp" "$OUT"

# Nol baytli fayl — buzilgan pipe belgisi
if [ ! -s "$OUT" ]; then
    echo "[$(date -u +%FT%TZ)] BACKUP FAILED — bo'sh fayl, o'chirilyapti" >&2
    rm -f "$OUT"
    exit 1
fi

SIZE=$(du -h "$OUT" | cut -f1)
echo "[$(date -u +%FT%TZ)] backup ok: $SIZE"

# Eski nusxalarni tozalash (retention)
find /backups -name 'zet-*.sql.gz' -type f -mtime "+${RETENTION_DAYS}" -delete -print 2>/dev/null || true
echo "[$(date -u +%FT%TZ)] retention: ${RETENTION_DAYS} kundan eski nusxalar tozalandi"
