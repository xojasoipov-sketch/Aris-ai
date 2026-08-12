# ZET web — ko'p bosqichli build (Hetzner/Docker uchun).
#
# NEGA KERAK BO'LDI. Railway'da frontend RAILPACK (nixpacks) orqali
# quriladi — Dockerfile shart emas edi. O'z serverida (Hetzner)
# `docker compose` bilan ishga tushirish uchun aniq Dockerfile kerak.
#
# `next.config.ts`da `output: "standalone"` YO'Q — shuning uchun bu
# yerda to'liq `node_modules` bilan quriladi (standalone'ga o'tish
# image hajmini kichraytiradi, lekin next.config'ni o'zgartirish
# alohida qaror bo'lishi kerak).

FROM node:22-bookworm-slim AS base
# Aniq versiya bilan — `corepack enable` + "latest" so'rovi EMAS.
# Repo pnpm-lock.yaml `lockfileVersion: 9.0`, ya'ni pnpm 9.x kerak.
# "latest"ni so'rash build vaqtida tashqi tarmoqqa qaram qiladi va
# versiya tasodifan o'zgarib qolishi mumkin.
RUN corepack enable && corepack prepare pnpm@9 --activate

FROM base AS deps
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Build vaqtida kerak bo'lishi mumkin bo'lgan public env — hozircha
# barcha ZET_API_TOKEN kabi sirlar RUNTIME'da (server route handler
# ichida) o'qiladi, build vaqtida kerak emas.
RUN pnpm build

# `corepack`SIZ — runtime bosqichi `base`dan EMAS, toza `node` rasmidan
# boshlanadi. Sabab mahalliy sinovda topildi: `pnpm start` konteyner
# ISHGA TUSHGANDA ham corepack orqali "eng so'nggi pnpm versiyasi"ni
# npmjs.org'dan so'raydi — build vaqtidagi pin (`corepack prepare`)
# runtime chaqiruvida hisobga olinmaydi. Natija: agar server ishga
# tushish payti npm registry'ga (yoki DNS'ga) qisqa muddat yeta
# olmasa, ZET frontend butunlay ko'tarilmaydi — build muvaffaqiyatli
# bo'lsa ham. `next` binaryni to'g'ridan-to'g'ri chaqirish bu tarmoq
# bog'liqligini butunlay olib tashlaydi.
FROM node:22-bookworm-slim AS runtime
# UID/GID 1000 EMAS — `node:*-bookworm-slim` rasmi allaqachon shu
# ID'da `node` foydalanuvchisini o'z ichiga oladi (backend'ning
# python-slim rasmida bunday emas edi, shuning uchun bu farq mahalliy
# build orqaligina topildi).
RUN groupadd --gid 1001 zet \
    && useradd --uid 1001 --gid zet --create-home zet
WORKDIR /app

# `public/` YO'Q bu loyihada — `COPY`ni majburiy manba talab qilgani
# uchun uni qo'shish build'ni yiqitardi (mahalliy build orqali topildi).
COPY --from=builder --chown=zet:zet /app/.next ./.next
COPY --from=builder --chown=zet:zet /app/node_modules ./node_modules
COPY --from=builder --chown=zet:zet /app/package.json ./package.json
COPY --from=builder --chown=zet:zet /app/next.config.ts ./next.config.ts

ENV NODE_ENV=production \
    PORT=3000

USER zet
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "require('http').get('http://localhost:3000', r => process.exit(r.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))"

CMD ["node_modules/.bin/next", "start", "-p", "3000"]
