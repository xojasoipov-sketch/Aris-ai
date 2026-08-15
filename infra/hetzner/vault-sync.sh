#!/bin/sh
# ZET — Obsidian vault git-sync (Obsidian-connection variant "b").
#
# `note.write`/`note.read`/`note.list` `/data/vault`da (nomlangan
# `vault_data` volume) ishlaydi — bu server ICHIDA doimiy, lekin
# Boss'ning o'z kompyuteridagi Obsidian ilovasi bilan avtomatik
# bog'lanmaydi. Bu skript shu papkani tashqi git repo bilan
# sinxronlaydi (Obsidian Git plugin xuddi shu repo'ni klonlab
# ishlatishi mumkin — ikkala tomon ham git orqali gaplashadi).
#
# XAVFSIZLIK QOIDASI (GAP bo'yicha o'rganilgan saboq — hech qachon
# sukut bo'yicha ma'lumot yo'qotilmasin):
#   - HECH QACHON force-push qilinmaydi.
#   - Rebase ziddiyatga uchrasa — `--abort` bilan orqaga qaytariladi,
#     mahalliy commit saqlanib qoladi (push qilinmagan holda), xato
#     ochiq log qilinadi. Avtomatik "hal qilish" yo'q.
#   - Remote sozlanmagan bo'lsa — jimgina o'chirilgan holatda qoladi
#     (xato emas, faqat bitta log qatori — recipes.py'dagi
#     MISSING_CAPABILITY falsafasi bilan bir xil).
set -eu

VAULT_DIR="/data/vault"
REMOTE="${ZET_VAULT_GIT_REMOTE:-}"
BRANCH="${ZET_VAULT_GIT_BRANCH:-main}"

log() { printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$1"; }

if [ -z "$REMOTE" ]; then
    log "ZET_VAULT_GIT_REMOTE bo'sh — vault-sync o'chirilgan (faqat lokal volume, tashqi git yo'q)."
    exit 0
fi

git config --global user.email "zet-vault-sync@localhost"
git config --global user.name "ZET vault-sync"
git config --global --add safe.directory "$VAULT_DIR"
git config --global init.defaultBranch "$BRANCH"

cd "$VAULT_DIR"

# ── Birinchi sozlash ─────────────────────────────────────────────
if [ ! -d .git ]; then
    log "birinchi sozlash: $REMOTE ($BRANCH)"
    git init -q
    git remote add origin "$REMOTE"

    if git ls-remote --exit-code --heads "$REMOTE" "$BRANCH" >/dev/null 2>&1; then
        # Remote'da branch bor — mavjud tarixni olib, mahalliy fayllarni
        # (agar Railway'dan ko'chirilgan bo'lsa) ustiga QO'SHAMIZ,
        # hech narsa o'chirmasdan.
        git fetch origin "$BRANCH" -q
        git checkout -q -B "$BRANCH" "origin/$BRANCH"
        log "remote tarix bilan boshlandi."
    else
        # Remote bo'sh/branch yo'q — mahalliy holatdan boshlanadi.
        git checkout -q -B "$BRANCH"
        log "remote bo'sh — mahalliy holatdan yangi tarix boshlanadi."
    fi
fi

# ── Mahalliy o'zgarishlarni commit qilish ────────────────────────
git add -A
if ! git diff --cached --quiet; then
    git commit -q -m "vault-sync: auto $(date -u +%FT%TZ)"
    log "mahalliy o'zgarishlar commit qilindi."
fi

# ── Remote'dan tortish (rebase, ziddiyatda AVTOMATIK ORQAGA) ────
if ! git pull --rebase --autostash -q origin "$BRANCH"; then
    log "ZIDDIYAT — rebase orqaga qaytarilmoqda, mahalliy commit saqlanadi (push QILINMADI)."
    git rebase --abort 2>/dev/null || true
    exit 1
fi

# ── Push (force YO'Q) ─────────────────────────────────────────────
if ! git push -q origin "HEAD:$BRANCH"; then
    log "PUSH MUVAFFAQIYATSIZ — keyingi tsiklda qayta urinilady, ma'lumot mahalliy saqlangan."
    exit 1
fi

log "sinxronlandi."
