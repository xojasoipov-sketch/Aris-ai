#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════
# ZET — lokal ishga tushirish (bitta buyruq)
#
# Ishlatish (repo ildizidan):
#     bash scripts/start-local.sh
#
# Nima qiladi:
#     1. Kerakli dasturlarni tekshiradi (docker, uv, node)
#     2. Postgres + Redis ko'taradi
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

need docker "https://docs.docker.com/get-docker/"
need node   "https://nodejs.org (20+ versiya)"
need npm    "Node.js bilan birga keladi"

if ! command -v uv >/dev/null 2>&1; then
  die "'uv' topilmadi. O'rnating: curl -LsSf https://astral.sh/uv/install.sh | sh"
fi

docker info >/dev/null 2>&1 || die "Docker ishlamayapti. Docker Desktop'ni ishga tushiring."

ok "docker · uv · node $(node --version)"

# ── 2. Postgres + Redis ────────────────────────────────────────────
step "Postgres + Redis ko'tarilmoqda"
docker compose -f infra/docker-compose.yml up -d --wait
ok "postgres:5432 · redis:6379"

# ── 3. Backend konfiguratsiyasi ────────────────────────────────────
step "Backend konfiguratsiyasi (.env)"

if [ ! -f "$CORE/.env" ]; then
  cp "$CORE/.env.example" "$CORE/.env"
  ok ".env yaratildi (.env.example dan)"
fi

# ZET_API_TOKEN bo'sh bo'lsa — tasodifiy qiymat yozamiz.
CURRENT_TOKEN="$(grep -E '^ZET_API_TOKEN=' "$CORE/.env" | head -1 | cut -d= -f2- | tr -d '[:space:]')"

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
step "Frontend dependency o'rnatilmoqda"
(cd "$WEB" && npm install --no-audit --no-fund)
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
  printf "  Postgres/Redis konteynerlari ishlab turibdi. To'xtatish: make down\n"
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

(cd "$WEB" && npm run dev) > "$LOG_DIR/web.log" 2>&1 &
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

cat <<EOF

${G}${B}════════════════════════════════════════════${N}
${G}${B}  ZET ishga tushdi${N}
${G}${B}════════════════════════════════════════════${N}

  Brauzerda oching:  ${B}http://localhost:3000${N}

  Backend API:       http://localhost:8000
  API hujjatlari:    http://localhost:8000/docs

  Loglar:            .local-logs/backend.log
                     .local-logs/web.log

  To'xtatish:        Ctrl+C

EOF

wait
