# ZET yadro — ko'p bosqichli build
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependency qatlami — manba o'zgarganda qayta o'rnatilmasin.
# BuildKit cache mount ISHLATILMAYDI: Railway builder cache id'ga o'z
# prefiksini talab qiladi va portativlikni buzadi. Qatlam keshi
# (COPY pyproject/uv.lock alohida qadam) baribir qayta o'rnatishni
# oldini oladi.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY src ./src
RUN uv sync --frozen --no-dev


FROM python:3.12-slim-bookworm AS runtime

# root bo'lmagan foydalanuvchi (Z1.3 acceptance criteria)
RUN groupadd --gid 1000 zet \
    && useradd --uid 1000 --gid zet --create-home zet

WORKDIR /app

COPY --from=builder --chown=zet:zet /app/.venv /app/.venv
COPY --from=builder --chown=zet:zet /app/src /app/src
COPY --chown=zet:zet alembic.ini ./
COPY --chown=zet:zet alembic ./alembic

# Obsidian vault uchun mount nuqtasi — oldindan yaratib zet'ga
# beriladi, shunda prod'da (Hetzner) shu yo'lga bog'langan Docker
# volume birinchi marta ulanganda TO'G'RI egalik bilan boshlanadi
# (aks holda bo'sh volume root:root bo'lib qolib, non-root
# konteyner note.write'da "Permission denied" bilan yiqilardi).
RUN mkdir -p /data/vault && chown -R zet:zet /data/vault

# Lokal ovoz (STT/TTS, ADR-0007) model og'irliklari uchun doimiy hajm —
# xuddi /data/vault naqshiga o'xshab. IMAGE'GA BAKE QILINMAYDI (build
# vaqtida internet + GB'larcha yuklab olish talab qilardi, build'ni
# sekinlashtiradi va image hajmini keskin oshiradi) — buning o'rniga
# `scripts/prepare_voice_models.py` operator tomonidan Railway volume
# ulangandan keyin BIR MARTA ishga tushiriladi, keyin har redeploy'da
# saqlanadi (Postgres/vault volume'lari bilan bir xil naqsh). Skript
# ishga tushirilmaguncha `WhisperSTT`/`MmsTTS` `is_configured=False`
# qaytaradi va `get_stt()`/`get_tts()` fail-open bilan ElevenLabs/Azure/
# Stub'ga tushadi — hech narsa qulamaydi.
RUN mkdir -p /data/voice-models && chown -R zet:zet /data/voice-models

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER zet

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')"

CMD ["uvicorn", "zet.main:app", "--host", "0.0.0.0", "--port", "8000"]
