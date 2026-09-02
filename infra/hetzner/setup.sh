#!/usr/bin/env bash
# ZET — Hetzner (Ubuntu 22.04/24.04) bootstrap skripti.
#
# NIMA QILADI:
#   1. Tizim paketlarini yangilaydi, Docker + Compose plugin o'rnatadi
#   2. ufw firewall'ni sozlaydi (faqat SSH, 80, 443, 8000 ochiq)
#   3. Repo'ni klonlaydi (agar hali yo'q bo'lsa)
#   4. .env fayllarni shablon'dan yaratadi (BO'SH — siz to'ldirasiz)
#   5. Ollama modellarini oldindan tortib oladi (birinchi so'rov
#      sekin bo'lmasligi uchun)
#   6. `docker compose` bilan hammasini ishga tushiradi
#
# QAYTA ISHGA TUSHIRISH XAVFSIZ — idempotent: mavjud narsalar
# qayta o'rnatilmaydi, .env fayllar ustiga yozilmaydi.
#
# ISHLATISH:
#   curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/<branch>/infra/hetzner/setup.sh | bash
#   # yoki repo'ni qo'lda klonlab, shu skriptni ishga tushiring:
#   sudo bash infra/hetzner/setup.sh
#
# Bu skript hech qanday sirni o'zi yaratmaydi yoki qayerdandir
# o'qimaydi — barcha API kalitlar/tokenlar SIZ tomondan `.env`
# fayllarga to'ldiriladi, to'g'ridan-to'g'ri serverda.

set -euo pipefail

REPO_URL="${ZET_REPO_URL:-https://github.com/xojasoipov-sketch/aris-ai.git}"
REPO_BRANCH="${ZET_REPO_BRANCH:-claude/zetproject-audit-plan-p9lysv}"
INSTALL_DIR="${ZET_INSTALL_DIR:-/opt/zet}"

log() { printf '\n\033[1;32m[zet-setup]\033[0m %s\n' "$1"; }
warn() { printf '\n\033[1;33m[zet-setup]\033[0m %s\n' "$1"; }

if [[ $EUID -ne 0 ]]; then
    warn "root bilan ishga tushiring: sudo bash setup.sh"
    exit 1
fi

# ── 1. Tizim paketlari + Docker ────────────────────────────────────
log "Tizim paketlari yangilanmoqda..."
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg ufw git >/dev/null

if ! command -v docker >/dev/null 2>&1; then
    log "Docker o'rnatilmoqda..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    . /etc/os-release
    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin >/dev/null
else
    log "Docker allaqachon o'rnatilgan — o'tkazib yuborildi."
fi

# ── 2. Firewall ─────────────────────────────────────────────────────
log "ufw sozlanmoqda (SSH + 80 + 443 + 8000)..."
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw allow 8000/tcp >/dev/null   # faqat domensiz (IP:port) rejim uchun
ufw --force enable >/dev/null

# ── 3. Repo ──────────────────────────────────────────────────────
if [[ -d "$INSTALL_DIR/.git" ]]; then
    log "Repo mavjud ($INSTALL_DIR) — yangilanmoqda..."
    git -C "$INSTALL_DIR" fetch origin "$REPO_BRANCH"
    git -C "$INSTALL_DIR" checkout "$REPO_BRANCH"
    git -C "$INSTALL_DIR" pull origin "$REPO_BRANCH"
else
    log "Repo klonlanmoqda ($REPO_URL @ $REPO_BRANCH)..."
    git clone --branch "$REPO_BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR/infra/hetzner"

# ── 4. .env fayllar ─────────────────────────────────────────────
if [[ ! -f .env ]]; then
    cp .env.example .env
    warn ".env yaratildi — TO'LDIRISHNI UNUTMANG: nano $INSTALL_DIR/infra/hetzner/.env"
    warn "  Kamida: POSTGRES_PASSWORD va ZET_API_TOKEN majburiy."
else
    log ".env allaqachon mavjud — o'zgartirilmadi."
fi

if [[ ! -f .env.web ]]; then
    cp .env.web.example .env.web
    warn ".env.web yaratildi — ZET_API_TOKEN'ni .env bilan BIR XIL qiling."
else
    log ".env.web allaqachon mavjud — o'zgartirilmadi."
fi

# ── 5. .env to'liqligini tekshirish ──────────────────────────────
# shellcheck disable=SC1091
source .env
if [[ -z "${POSTGRES_PASSWORD:-}" || -z "${ZET_API_TOKEN:-}" ]]; then
    warn "======================================================================"
    warn " .env HALI TO'LIQ EMAS."
    warn " POSTGRES_PASSWORD va ZET_API_TOKEN'ni to'ldiring, so'ng qayta ishga"
    warn " tushiring:"
    warn "   nano $INSTALL_DIR/infra/hetzner/.env"
    warn "   nano $INSTALL_DIR/infra/hetzner/.env.web   (ZET_API_TOKEN bir xil)"
    warn "   sudo bash $INSTALL_DIR/infra/hetzner/setup.sh"
    warn "======================================================================"
    exit 1
fi

# Domen bo'lsa — Caddyfile domen bilan, bo'lmasa IP:port rejimi.
#
# `Caddyfile.active` — repo'da KUZATILMAYDIGAN fayl (.gitignore), har
# ishga tushirishda shu yerda qayta yaratiladi. Asl `Caddyfile`/
# `Caddyfile.no-domain` `git pull`da yangilanadi, `.active` esa
# compose'ning o'qiydigan nusxasi — shu bilan tracked fayl hech qachon
# mahalliy o'zgartirilmaydi (keyingi `git pull`da conflict bo'lmaydi).
if [[ -n "${ZET_DOMAIN:-}" && -n "${ZET_API_DOMAIN:-}" ]]; then
    log "Domen aniqlandi: $ZET_DOMAIN / $ZET_API_DOMAIN — avtomatik TLS."
    cp Caddyfile Caddyfile.active
else
    warn "Domen berilmagan — IP:port rejimi (TLS YO'Q). Ishlatish uchun:"
    warn "  Web:     http://<server-ip>"
    warn "  Backend: http://<server-ip>:8000"
    cp Caddyfile.no-domain Caddyfile.active
fi

# ── 6. Ollama modellarini oldindan tortish ────────────────────────
log "Docker compose ishga tushirilmoqda (birinchi build biroz vaqt oladi)..."
docker compose -f docker-compose.prod.yml --env-file .env up -d --build postgres redis ollama

log "Ollama modellarini yuklab olish (bir martalik, ~5-10 daqiqa)..."
docker exec zet-ollama ollama pull "${ZET_OLLAMA_MODEL:-qwen3:8b}" || warn "qwen3:8b tortib bo'lmadi — keyinroq qo'lda: docker exec zet-ollama ollama pull qwen3:8b"
docker exec zet-ollama ollama pull "${ZET_OLLAMA_EMBED_MODEL:-bge-m3}" || warn "bge-m3 tortib bo'lmadi — keyinroq qo'lda: docker exec zet-ollama ollama pull bge-m3"

log "Backend + web + Caddy ishga tushirilmoqda..."
docker compose -f docker-compose.prod.yml --env-file .env up -d --build

log "Tayyor. Holatni tekshirish: docker compose -f docker-compose.prod.yml ps"
log "Log'larni ko'rish:          docker compose -f docker-compose.prod.yml logs -f backend"
