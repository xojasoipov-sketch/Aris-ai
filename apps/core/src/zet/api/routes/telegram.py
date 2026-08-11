"""Telegram API endpoint'lari (Bo'lim 5).

Telegram bot bilan ishlaydigan API:
    POST /api/v1/telegram/message   — xabar qayta ishlash (test/webhook)
    GET  /api/v1/telegram/status    — bot holati

Bog'liq qarorlar:
    V-17 — Telegram = asosiy boshqaruv paneli
    ADR-0007 — long polling (lekin webhook ham tayyor)
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from zet.api.deps import get_telegram_bot
from zet.telegram.bot import ZetBot

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/telegram", tags=["telegram"])


# ── Request / Response modellari ──────────────────────────────────


class TelegramMessageRequest(BaseModel):
    """Telegram xabar qayta ishlash so'rovi (test/webhook)."""

    user_id: int
    chat_id: int
    text: str | None = None
    callback_data: str | None = None
    # Voice/photo/document — bo'lim 8 da to'liq qo'llab-quvvatlanadi


class TelegramMessageResponse(BaseModel):
    """Telegram xabar javobi."""

    success: bool
    text: str | None = None
    parse_mode: str | None = None


class TelegramStatusResponse(BaseModel):
    """Telegram bot holati."""

    running: bool
    owner_count: int
    has_token: bool


# ── Endpoint'lar ──────────────────────────────────────────────────


@router.post("/message", response_model=TelegramMessageResponse, status_code=200)
async def process_message(
    request: TelegramMessageRequest,
    bot: ZetBot = Depends(get_telegram_bot),
) -> TelegramMessageResponse:
    """Xabarni qayta ishlash (test/webhook uchun).

    Owner tekshiruvi bot ichida amalga oshiriladi.
    """
    result = await bot.process_message(
        user_id=request.user_id,
        chat_id=request.chat_id,
        text=request.text,
        callback_data=request.callback_data,
    )

    if result is None:
        return TelegramMessageResponse(
            success=False,
            text=None,
        )

    return TelegramMessageResponse(
        success=True,
        text=result.text,
        parse_mode=result.parse_mode,
    )


@router.get("/status", response_model=TelegramStatusResponse)
async def bot_status(
    bot: ZetBot = Depends(get_telegram_bot),
) -> TelegramStatusResponse:
    """Bot holati."""
    return TelegramStatusResponse(
        running=bot.is_running,
        owner_count=len(bot.owner_middleware.owner_ids),
        has_token=bool(bot._token),
    )
