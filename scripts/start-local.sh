#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════
# ZET — lokal ishga tushirish (bitta buyruq)
#
# Ishlatish (repo ildizidan):
#     bash scripts/start-local.sh
#
# Nima qiladi:
#     1. Kerakli dasturlarni tekshiradi (node majburiy; uv yo'q bo'lsa
#        o'zi o'rnatadi; docker ixtiyoriy)
#     2. Docker bo'lsa — Postgres + Redis ko'taradi.
#        Docker bo'lmasa — SQLite'ga tushadi (dev rejim, hech narsa
#        o'rnatish shart emas)
#     3. apps/core/.env yaratadi (yo'q bo'lsa) — ZET_API_TOKEN avtomatik
#     4. Python dependency + migratsiya
#     5. apps/web/.env.local yaratadi (token backend bilan bir xil)
#     6. npm install
#     7. Backend (8000) + frontend (3000) ni ishga tushiradi
#
# TO'XTATISH: Ctrl+C (ikkala server ham to'xtaydi; Postgres/Redis
# konteynerlari qoladi — ularni `make down` bilan to'xtatasiz).
#
# XAVFSIZLIK: bu skript hech qanday sirni tarmoqqa yubormaydi.
# ZET_API_TOKEN faqat lokal fayllarga yoziladi (.env, .env.local) —
# ikkalasi ham .gitignore ichida.
# ════════════════════════════════════════════════════════════════════

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

CORE="$REPO_ROOT/apps/core"
WEB="$REPO_ROOT/apps/web"

# ── Ranglar (terminal qo'llab-quvvatlasa) ──────────────────────────
if [ -t 1 ]; then
  B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; N=$'\033[0m'
else
  B=""; G=""; Y=""; R=""; N=""
fi

step() { printf "\n%s▸ %s%s\n" "$B" "$1" "$N"; }
ok()   { printf "  %s✓%s %s\n" "$G" "$N" "$1"; }
warn() { printf "  %s!%s %s\n" "$Y" "$N" "$1"; }
die()  { printf "\n%s✗ %s%s\n" "$R" "$1" "$N" >&2; exit 1; }

# ── 1. Kerakli dasturlar ───────────────────────────────────────────
step "Kerakli dasturlar tekshirilmoqda"

need() {
  command -v "$1" >/dev/null 2>&1 || die "'$1' topilmadi. O'rnating: $2"
}

# Node — MAJBURIY (frontend'siz ishlab bo'lmaydi).
need node "https://nodejs.org (20+ versiya)"
need npm  "Node.js bilan birga keladi (pnpm o'rnatish uchun kerak)"

# uv — yo'q bo'lsa o'zimiz o'rnatamiz (~/.local/bin ichiga, tizimga tegmaydi).
if ! command -v uv >/dev/null 2>&1; then
  warn "'uv' topilmadi — o'rnatilmoqda..."
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 \
    || die "uv o'rnatilmadi. Qo'lda: curl -LsSf https://astral.sh/uv/install.sh | sh"
  # O'rnatuvchi shu ikki joydan biriga qo'yadi — PATH'ga qo'shamiz.
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 || die "uv o'rnatildi, lekin PATH'da topilmadi. Terminalni qayta oching."
  ok "uv o'rnatildi"
fi

# Docker — IXTIYORIY. Bo'lmasa SQLite'ga tushamiz.
DB_MODE="postgres"
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  ok "docker · uv · node $(node --version)"
else
  DB_MODE="sqlite"
  if command -v docker >/dev/null 2>&1; then
    warn "Docker o'rnatilgan, lekin ishlamayapti (Docker Desktop yopiq?)."
  else
    warn "Docker topilmadi."
  fi
  warn "SQLite rejimiga o'tildi — hech narsa o'rnatish shart emas."
  warn "Bu DEV rejim: ma'lumot ./apps/core/data/zet.db faylida saqlanadi."
  warn "Postgres rejimi uchun Docker Desktop'ni o'rnatib skriptni qayta ishga tushiring."
  ok "uv · node $(node --version)"
fi

# ── 2. Postgres + Redis ────────────────────────────────────────────
if [ "$DB_MODE" = "postgres" ]; then
  step "Postgres + Redis ko'tarilmoqda"
  docker compose -f infra/docker-compose.yml up -d --wait
  ok "postgres:5432 · redis:6379"
fi

# ── 3. Backend konfiguratsiyasi ────────────────────────────────────
step "Backend konfiguratsiyasi (.env)"

if [ ! -f "$CORE/.env" ]; then
  cp "$CORE/.env.example" "$CORE/.env"
  ok ".env yaratildi (.env.example dan)"
fi

# .env qatoridan qiymat ajratish.
# MUHIM: `.env.example` da qiymatlardan keyin satr-ichi izoh bor
#   ZET_API_TOKEN=                   # prod'da MAJBURIY
# `sed 's/#.*//'` bo'lmasa, o'sha izoh TOKEN deb o'qiladi va frontend'ga
# axlat qiymat yoziladi (dotenv esa backend tomonda izohni tashlab,
# tokenni bo'sh deb ko'radi) — natijada hamma so'rov 401 bo'lardi.
env_value() {
  grep -E "^$1=" "$CORE/.env" | head -1 | cut -d= -f2- | sed 's/#.*//' | tr -d '[:space:]'
}

CURRENT_TOKEN="$(env_value ZET_API_TOKEN)"

if [ -z "$CURRENT_TOKEN" ]; then
  if command -v openssl >/dev/null 2>&1; then
    NEW_TOKEN="$(openssl rand -hex 32)"
  else
    NEW_TOKEN="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  fi
  # macOS/BSD sed va GNU sed ikkalasida ham ishlaydigan usul:
  tmp="$(mktemp)"
  sed "s|^ZET_API_TOKEN=.*|ZET_API_TOKEN=${NEW_TOKEN}|" "$CORE/.env" > "$tmp"
  mv "$tmp" "$CORE/.env"
  CURRENT_TOKEN="$NEW_TOKEN"
  ok "ZET_API_TOKEN avtomatik yaratildi"
else
  ok "ZET_API_TOKEN allaqachon o'rnatilgan"
fi

# SQLite rejimida — DB manzilini almashtiramiz.
# DIQQAT: faqat manzil hali lokal Postgres'ga qaragan bo'lsa tegamiz.
# Foydalanuvchi o'zi boshqa DB yozgan bo'lsa — tegmaymiz.
if [ "$DB_MODE" = "sqlite" ]; then
  mkdir -p "$CORE/data"
  CURRENT_DB="$(env_value ZET_DATABASE_URL)"
  case "$CURRENT_DB" in
    *localhost:5432*|*127.0.0.1:5432*|"")
      tmp="$(mktemp)"
      sed "s|^ZET_DATABASE_URL=.*|ZET_DATABASE_URL=sqlite+aiosqlite:///./data/zet.db|" \
        "$CORE/.env" > "$tmp"
      mv "$tmp" "$CORE/.env"
      ok "ZET_DATABASE_URL → SQLite (apps/core/data/zet.db)"
      ;;
    *)
      warn "ZET_DATABASE_URL o'zgartirilmadi (siz o'zingiz sozlagansiz):"
      warn "  $CURRENT_DB"
      ;;
  esac
fi

# LLM kaliti bormi — ogohlantirish (majburiy emas, lekin ZET aqlsiz bo'ladi)
if ! grep -qE '^ZET_(GOOGLE|GROQ|MISTRAL|OPENROUTER|ANTHROPIC|OPENAI)_API_KEY=.+' "$CORE/.env"; then
  warn "Hech qanday LLM kaliti yo'q — ZET javob bera olmaydi."
  warn "apps/core/.env ichiga ZET_GOOGLE_API_KEY yoki ZET_GROQ_API_KEY qo'shing (bepul)."
fi

# ── 4. Python dependency + migratsiya ──────────────────────────────
step "Python dependency o'rnatilmoqda (birinchi marta ~2-5 daqiqa)"
(cd "$CORE" && uv sync --all-extras)
ok "dependency tayyor"

step "Ma'lumotlar bazasi migratsiyasi"
(cd "$CORE" && uv run alembic upgrade head)
ok "sxema qo'llandi"

# ── 5. Frontend konfiguratsiyasi ───────────────────────────────────
step "Frontend konfiguratsiyasi (.env.local)"
cat > "$WEB/.env.local" <<EOF
# Avtomatik yaratildi: scripts/start-local.sh
# Token backend'dagi apps/core/.env bilan bir xil bo'lishi SHART.
ZET_API_URL=http://localhost:8000
ZET_API_TOKEN=${CURRENT_TOKEN}
EOF
ok ".env.local yozildi (token backend bilan bir xil)"

# ── 6. npm dependency ──────────────────────────────────────────────
# Loyiha pnpm ishlatadi — `apps/web/pnpm-lock.yaml` commit qilingan va
# `apps/web/Dockerfile` ham `pnpm install --frozen-lockfile` qiladi.
# `npm install` bu yerda XATO: lockfile'ni e'tiborsiz qoldiradi va
# pnpm yaratgan node_modules ustida "Cannot read properties of null"
# bilan yiqiladi (mahalliy sinovda tasdiqlangan).
step "Frontend dependency o'rnatilmoqda (pnpm)"

if ! command -v pnpm >/dev/null 2>&1; then
  if command -v corepack >/dev/null 2>&1; then
    warn "pnpm topilmadi — corepack orqali o'rnatilmoqda..."
    corepack enable >/dev/null 2>&1 || true
    corepack prepare pnpm@9 --activate >/dev/null 2>&1 || true
  fi
fi
if ! command -v pnpm >/dev/null 2>&1; then
  warn "pnpm hali yo'q — npm orqali global o'rnatilmoqda..."
  npm install -g pnpm@9 >/dev/null 2>&1 \
    || die "pnpm o'rnatilmadi. Qo'lda: npm install -g pnpm@9"
fi

# Avval lockfile'ga qat'iy rioya qilamiz (Dockerfile bilan bir xil).
# Lockfile package.json'dan orqada qolgan bo'lsa — yumshoqroq rejim.
if ! (cd "$WEB" && pnpm install --frozen-lockfile 2>/dev/null); then
  warn "Lockfile package.json bilan mos emas — oddiy o'rnatishga o'tildi."
  (cd "$WEB" && pnpm install)
fi
ok "node_modules tayyor"

# ── 7. Ishga tushirish ─────────────────────────────────────────────
step "Serverlar ishga tushirilmoqda"

LOG_DIR="$REPO_ROOT/.local-logs"
mkdir -p "$LOG_DIR"

cleanup() {
  printf "\n%s▸ To'xtatilmoqda...%s\n" "$B" "$N"
  [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" 2>/dev/null || true
  [ -n "${WEB_PID:-}" ]     && kill "$WEB_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  if [ "${DB_MODE:-}" = "postgres" ]; then
    printf "  Postgres/Redis konteynerlari ishlab turibdi. To'xtatish: make down\n"
  fi
}
trap cleanup EXIT INT TERM

(cd "$CORE" && uv run uvicorn zet.main:app --host 127.0.0.1 --port 8000) \
  > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

# Backend ko'tarilishini kutamiz (maks 60s)
printf "  backend kutilmoqda"
for i in $(seq 1 60); do
  if curl -sf http://localhost:8000/api/v1/health >/dev/null 2>&1 \
     || curl -sf http://localhost:8000/docs >/dev/null 2>&1; then
    printf "\n"; ok "backend → http://localhost:8000"
    break
  fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    printf "\n"
    printf "%s✗ Backend ishga tushmadi. Oxirgi loglar:%s\n" "$R" "$N" >&2
    tail -30 "$LOG_DIR/backend.log" >&2
    exit 1
  fi
  printf "."
  sleep 1
done

(cd "$WEB" && pnpm dev) > "$LOG_DIR/web.log" 2>&1 &
WEB_PID=$!

printf "  frontend kutilmoqda"
for i in $(seq 1 90); do
  if curl -sf http://localhost:3000 >/dev/null 2>&1; then
    printf "\n"; ok "frontend → http://localhost:3000"
    break
  fi
  if ! kill -0 "$WEB_PID" 2>/dev/null; then
    printf "\n"
    printf "%s✗ Frontend ishga tushmadi. Oxirgi loglar:%s\n" "$R" "$N" >&2
    tail -30 "$LOG_DIR/web.log" >&2
    exit 1
  fi
  printf "."
  sleep 1
done

if [ "$DB_MODE" = "postgres" ]; then
  DB_LABEL="Postgres (docker)"
else
  DB_LABEL="SQLite — apps/core/data/zet.db (dev rejim)"
fi

cat <<EOF

${G}${B}════════════════════════════════════════════${N}
${G}${B}  ZET ishga tushdi${N}
${G}${B}════════════════════════════════════════════${N}

  Brauzerda oching:  ${B}http://localhost:3000${N}

  Backend API:       http://localhost:8000
  API hujjatlari:    http://localhost:8000/docs

  Ma'lumotlar bazasi: ${DB_LABEL}

  Loglar:            .local-logs/backend.log
                     .local-logs/web.log

  To'xtatish:        Ctrl+C

EOF

wait
