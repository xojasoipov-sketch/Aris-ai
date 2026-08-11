"""Push bildirishnomalar — egasiga xabar yuborish (V-17).

Xabar turlari:
    - Oddiy matnli xabar
    - Approval so'rovi (inline tugmalar bilan)
    - Task natijasi (muvaffaqiyat/muvaffaqiyatsiz)
    - Agent bildirishnomasi
    - Alert (xavfli holat)

Bo'lim 5 lean: in-memory queue, haqiqiy Telegram yuborish aiogram bilan.
Test rejimda StubNotifier ishlatiladi.

Bog'liq qarorlar:
    V-17 — OUT: answers, alerts, task results, reports, approval requests
    V-32 — approval so'rovlari inline tugmalar bilan
"""

from __future__ import annotations

import abc
from datetime import UTC, datetime
from enum import StrEnum

import structlog
from pydantic import BaseModel, Field

from zet.telegram.keyboards import InlineKeyboard

log = structlog.get_logger(__name__)


class NotificationType(StrEnum):
    """Bildirishnoma turi."""

    MESSAGE = "message"
    """Oddiy matnli xabar."""

    APPROVAL = "approval"
    """Tasdiq so'rovi — inline tugmalar bilan."""

    TASK_RESULT = "task_result"
    """Task natijasi."""

    AGENT_ALERT = "agent_alert"
    """Agent bildirishnomasi."""

    SYSTEM_ALERT = "system_alert"
    """Tizim ogohlantirishi."""


class Notification(BaseModel, frozen=True):
    """Bildirishnoma modeli."""

    type: NotificationType
    """Bildirishnoma turi."""

    text: str
    """Xabar matni."""

    keyboard: InlineKeyboard | None = None
    """Ixtiyoriy inline klaviatura."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Yaratilgan vaqt."""

    run_id: str | None = None
    """Bog'liq run identifikatori."""

    agent_name: str | None = None
    """Bog'liq agent nomi."""

    model_config = {"arbitrary_types_allowed": True}


class Notifier(abc.ABC):
    """Bildirishnoma yuboruvchi interfeys."""

    @abc.abstractmethod
    async def send(self, notification: Notification) -> bool:
        """Bildirishnoma yuborish.

        Args:
            notification: yuborilishi kerak bo'lgan bildirishnoma

        Returns:
            True agar muvaffaqiyatli yuborilsa
        """

    async def send_text(self, text: str) -> bool:
        """Oddiy matnli xabar yuborish."""
        return await self.send(Notification(type=NotificationType.MESSAGE, text=text))

    async def send_approval(
        self,
        text: str,
        keyboard: InlineKeyboard,
        run_id: str | None = None,
    ) -> bool:
        """Tasdiq so'rovi yuborish."""
        return await self.send(
            Notification(
                type=NotificationType.APPROVAL,
                text=text,
                keyboard=keyboard,
                run_id=run_id,
            )
        )

    async def send_task_result(
        self,
        text: str,
        run_id: str | None = None,
        agent_name: str | None = None,
    ) -> bool:
        """Task natijasi yuborish."""
        return await self.send(
            Notification(
                type=NotificationType.TASK_RESULT,
                text=text,
                run_id=run_id,
                agent_name=agent_name,
            )
        )

    async def send_alert(self, text: str) -> bool:
        """Tizim ogohlantirishi yuborish."""
        return await self.send(Notification(type=NotificationType.SYSTEM_ALERT, text=text))


class StubNotifier(Notifier):
    """Test uchun stub — xabarlarni in-memory ro'yxatga saqlaydi."""

    def __init__(self) -> None:
        self.sent: list[Notification] = []

    async def send(self, notification: Notification) -> bool:
        """Stub: xabarni ro'yxatga qo'shadi."""
        self.sent.append(notification)
        log.info(
            "notifier.stub_send",
            type=notification.type.value,
            text=notification.text[:100],
        )
        return True

    @property
    def count(self) -> int:
        """Yuborilgan xabarlar soni."""
        return len(self.sent)

    def clear(self) -> None:
        """Ro'yxatni tozalash."""
        self.sent.clear()
