#!/usr/bin/env bash
# ZET — serverdagi nusxani yangilash (Z49).
#
# `setup.sh` BIRINCHI o'rnatish uchun: apt paketlari, Docker, ufw,
# Ollama modellarini tortib olish. Ularning hammasi qayta ishga
# tushirishda keraksiz va sekin (10+ daqiqa).
#
# Bu skript faqat YANGILAYDI:
#   1. Yangi kodni tortadi (git pull)
#   2. Konteynerlarni qayta yig'adi va ishga tushiradi
#   3. Migratsiya avtomatik ketadi — `docker-compose.prod.yml` ichida
#      backend `alembic upgrade head` bilan boshlanadi
#   4. Sog'liqni tekshiradi va NIMA YETISHMAYOTGANINI aytadi
#
# ISHLATISH (serverda, bitta qator):
#   sudo bash /opt/zet/infra/hetzner/update.sh
#
# Ma'lumot YO'QOLMAYDI: Postgres va Ollama modellari alohida Docker
# volume'larda, ular qayta yig'ishda tegilmaydi.

set -euo pipefail

REPO_BRANCH="${ZET_REPO_BRANCH:-claude/zetproject-audit-plan-p9lysv}"
INSTALL_DIR="${ZET_INSTALL_DIR:-/opt/zet}"
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env"

log() { printf '\n\033[1;32m[zet-update]\033[0m %s\n' "$1"; }
warn() { printf '\n\033[1;33m[zet-update]\033[0m %s\n' "$1"; }
fail() { printf '\n\033[1;31m[zet-update]\033[0m %s\n' "$1"; }

if [[ $EUID -ne 0 ]]; then
    fail "root bilan ishga tushiring: sudo bash update.sh"
    exit 1
fi

if [[ ! -d "$INSTALL_DIR/.git" ]]; then
    fail "$INSTALL_DIR topilmadi. Avval setup.sh ishga tushiring."
    exit 1
fi

# ── 1. Yangi kod ───────────────────────────────────────────────────
log "Yangi kod tortilmoqda ($REPO_BRANCH)..."
git -C "$INSTALL_DIR" fetch origin "$REPO_BRANCH"
git -C "$INSTALL_DIR" checkout "$REPO_BRANCH"
git -C "$INSTALL_DIR" reset --hard "origin/$REPO_BRANCH"

cd "$INSTALL_DIR/infra/hetzner"

if [[ ! -f .env ]]; then
    fail ".env yo'q. setup.sh ishga tushiring."
    exit 1
fi

# Caddyfile.active — kuzatilmaydigan nusxa, `git reset` uni tiklamaydi.
if [[ ! -f Caddyfile.active ]]; then
    set +u
    # shellcheck disable=SC1091
    . ./.env
    if [[ -n "${ZET_DOMAIN:-}" && -n "${ZET_API_DOMAIN:-}" ]]; then
        cp Caddyfile Caddyfile.active
    else
        cp Caddyfile.no-domain Caddyfile.active
    fi
    set -u
fi

# ── 2. Qayta yig'ish ───────────────────────────────────────────────
log "Konteynerlar qayta yig'ilmoqda (2-5 daqiqa)..."
$COMPOSE up -d --build

log "Backend ko'tarilishi kutilmoqda (migratsiya ham shu yerda)..."
for _ in $(seq 1 60); do
    if curl -fsS -m 5 http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
        break
    fi
    sleep 5
done

# ── 3. Halol tekshiruv ─────────────────────────────────────────────
printf '\n\033[1m===== ZET HOLATI =====\033[0m\n'
$COMPOSE ps --format 'table {{.Service}}\t{{.Status}}' 2>/dev/null || $COMPOSE ps

if curl -fsS -m 5 http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
    log "Backend: SOG'LOM"
else
    fail "Backend javob bermayapti. Log: $COMPOSE logs --tail=50 backend"
    exit 1
fi

# Eng ko'p uchraydigan nosozlik: `.env`da birorta LLM kaliti yo'q va
# Ollama modeli tortilmagan. Bunda ZET ko'tariladi, lekin FIKRLAY
# OLMAYDI — har so'rov "provayder topilmadi" bilan yiqiladi. Buni
# jimgina qoldirish "ishlayapti" degan yolg'on taassurot berardi.
log "Fikrlash zanjiri tekshirilmoqda..."
if docker exec zet-ollama ollama list 2>/dev/null | grep -qE 'qwen3|llama|mistral'; then
    log "Ollama modeli: BOR"
else
    warn "OLLAMA MODELI YO'Q — ZET mahalliy model bilan fikrlay olmaydi."
    warn "  Tuzatish:  docker exec zet-ollama ollama pull qwen3:8b"
fi

if grep -qE '^ZET_(GOOGLE|MISTRAL|OPENROUTER|CEREBRAS|COHERE|ANTHROPIC|GROQ|KIMI|DEEPSEEK)_API_KEY=.+' .env; then
    log "Bulut LLM kaliti: BOR"
else
    warn "BULUT LLM KALITI YO'Q — faqat Ollama'ga tayanadi."
    warn "  Tuzatish:  nano $INSTALL_DIR/infra/hetzner/.env   (so'ng shu skriptni qayta ishga tushiring)"
fi

if grep -qE '^ZET_TELEGRAM_BOT_TOKEN=.+' .env; then
    log "Telegram: BOR"
else
    warn "TELEGRAM TOKENI YO'Q — kunlik hisobot va bildirishnomalar yuborilmaydi."
fi

printf '\n\033[1;32mTayyor.\033[0m Web: http://%s   Backend: http://%s:8000\n\n' \
    "$(curl -fsS -m 5 https://api.ipify.org 2>/dev/null || echo '<server-ip>')" \
    "$(curl -fsS -m 5 https://api.ipify.org 2>/dev/null || echo '<server-ip>')"
