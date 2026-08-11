"""Owner middleware — faqat egasiga ruxsat (A-05, R-04).

Xavfsizlik:
    1. Owner ID allowlist — faqat ro'yxatdagi Telegram user_id qabul qilinadi
    2. Noma'lum foydalanuvchi → xabar beriladi va log yoziladi
    3. Bot token o'g'irlanishi holatida ham faqat ega ishlatishi mumkin

Bog'liq qarorlar:
    A-05 — ishonch darajasi chegaralari (OWNER / SYSTEM / UNTRUSTED)
    R-04 — bot token xavfsizligi
    V-17 — Telegram = asosiy boshqaruv paneli
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# Type aliases — aiogram importlari runtime vaqtida yuklanadi
# chunki aiogram ixtiyoriy dependency


class OwnerMiddleware:
    """Faqat egasi Telegram user_id lariga ruxsat beruvchi middleware.

    Har bir kiruvchi xabarda user_id tekshiriladi.
    Ro'yxatda bo'lmagan foydalanuvchilarga xabar beriladi va skip qilinadi.

    Bu middleware aiogram 3 ning BaseMiddleware ga o'xshash ishlaydi,
    lekin aiogram ixtiyoriy bo'lgani uchun to'g'ridan-to'g'ri meros olmaydi.
    """

    def __init__(self, owner_ids: set[int]) -> None:
        """
        Args:
            owner_ids: ruxsat etilgan Telegram user_id lar to'plami.
                       Bo'sh bo'lsa — hech kimga ruxsat yo'q (fail-closed).
        """
        if not owner_ids:
            log.warning("owner_middleware.empty_allowlist")
        self._owner_ids = frozenset(owner_ids)

    @property
    def owner_ids(self) -> frozenset[int]:
        """Ruxsat etilgan user_id lar."""
        return self._owner_ids

    def is_owner(self, user_id: int) -> bool:
        """Foydalanuvchi egasimi tekshirish."""
        return user_id in self._owner_ids

    async def check(
        self,
        user_id: int,
        username: str | None = None,
    ) -> bool:
        """Foydalanuvchini tekshirish.

        Args:
            user_id: Telegram user ID
            username: Telegram username (log uchun)

        Returns:
            True agar ruxsat berilsa, False aks holda
        """
        if self.is_owner(user_id):
            log.debug(
                "owner_middleware.allowed",
                user_id=user_id,
                username=username,
            )
            return True

        log.warning(
            "owner_middleware.denied",
            user_id=user_id,
            username=username,
        )
        return False

    async def __call__(
        self,
        handler: Callable[..., Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        """aiogram 3 middleware interfeysi.

        Ruxsat berilmasa — handler chaqirilmaydi (skip).
        """
        # Event dan user_id olish
        user_id = _extract_user_id(event)
        username = _extract_username(event)

        if user_id is None:
            log.warning("owner_middleware.no_user_id", event_type=type(event).__name__)
            return None

        if not await self.check(user_id, username):
            # Ruxsat yo'q — javob bermaslik
            return None

        return await handler(event, data)


def _extract_user_id(event: Any) -> int | None:
    """Event dan user_id olish (turli event turlari uchun)."""
    # Message, CallbackQuery, va boshqalar uchun
    if hasattr(event, "from_user") and event.from_user is not None:
        return int(event.from_user.id)
    return None


def _extract_username(event: Any) -> str | None:
    """Event dan username olish."""
    if hasattr(event, "from_user") and event.from_user is not None:
        return event.from_user.username
    return None
