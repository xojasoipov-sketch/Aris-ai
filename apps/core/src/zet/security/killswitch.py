"""Emergency Stop (KillSwitch) — Z1.12.

Global bayroq — yoqilganda:
    1. Barcha faol run'lar bir zumda CANCELLED
    2. Yangi run boshlanmaydi
    3. Protsess qayta ishga tushsa ham kuchda qoladi (DB da saqlanadi)

Faqat eganing aniq buyrug'i bilan qaytariladi (`z resume`).

Bog'liq qarorlar:
    V-33 — favqulodda to'xtatish
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import structlog

log = structlog.get_logger(__name__)

EngageCallback = Callable[[], Awaitable[None] | None]
"""Kill-switch `engage()` chaqirilganda ishga tushadigan hook.

Sinxron yoki asinxron bo'lishi mumkin. Asinxron bo'lsa — joriy event
loop mavjud bo'lsa `create_task` orqali fon vazifasi sifatida ishga
tushiriladi (aks holda coroutine yopiladi). Har chaqiruv fail-open:
istisno faqat log yoziladi, `engage()` xato bermaydi.
"""


class KillSwitchEngagedError(Exception):
    """Kill switch yoqilgan — hech qanday amal bajarilmaydi."""


class KillSwitchState:
    """Kill switch holati — in-memory (DB bilan sinxronlash Orchestrator vazifasi).

    Thread-safe emas — async context'da ishlatiladi.
    """

    def __init__(self) -> None:
        self._engaged: bool = False
        self._reason: str | None = None
        self._engaged_at: datetime | None = None
        self._engaged_by: str | None = None
        self._engage_callbacks: list[EngageCallback] = []
        # `asyncio.create_task` natijasi zaif referens bilan garbage-collect
        # bo'lmasin uchun ushlab turamiz (ruff RUF006).
        self._callback_tasks: set[asyncio.Task[None]] = set()

    def register_engage_callback(self, callback: EngageCallback) -> None:
        """`engage()` chaqirilganda ishga tushadigan hook qo'shadi (SR-06).

        Kill-switch yoqilishi bilan capability tokenlarni bekor qilish,
        push bildirishnoma yuborish yoki boshqa yon ta'sirlar uchun.
        Callback sinxron yoki asinxron bo'lishi mumkin — asinxron bo'lsa
        joriy event loop mavjud bo'lganda fon vazifasi sifatida ishga
        tushiriladi. Har chaqiruv fail-open: hech qanday istisno
        `engage()`ni to'xtatmaydi.
        """
        self._engage_callbacks.append(callback)

    def clear_engage_callbacks(self) -> None:
        """Barcha ro'yxatga olingan callback'larni tozalaydi (testlar uchun)."""
        self._engage_callbacks.clear()

    def _fire_engage_callbacks(self) -> None:
        """`engage()` ichida chaqiriladi — hookarni yugurtiradi (fail-open)."""
        for cb in list(self._engage_callbacks):
            try:
                result = cb()
            except Exception:
                log.warning("killswitch.engage_callback_failed", exc_info=True)
                continue
            if inspect.isawaitable(result):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    # Event loop yo'q — coroutine'ni jimgina yopamiz,
                    # RuntimeWarning bermasin (`z killswitch on` CLI holati).
                    if hasattr(result, "close"):
                        result.close()  # type: ignore[union-attr]
                    continue
                task = loop.create_task(_swallow_async_callback(result))
                self._callback_tasks.add(task)
                task.add_done_callback(self._callback_tasks.discard)

    @property
    def is_engaged(self) -> bool:
        """Kill switch yoqilganmi."""
        return self._engaged

    @property
    def reason(self) -> str | None:
        """Yoqilish sababi."""
        return self._reason

    @property
    def engaged_at(self) -> datetime | None:
        """Yoqilgan vaqt."""
        return self._engaged_at

    @property
    def engaged_by(self) -> str | None:
        """Kim yoqqan."""
        return self._engaged_by

    def engage(
        self,
        *,
        reason: str = "Emergency stop",
        by: str = "owner",
        now: datetime | None = None,
    ) -> None:
        """Kill switch'ni yoqadi.

        Idempotent — allaqachon yoqilgan bo'lsa hech narsa qilmaydi.
        """
        if self._engaged:
            log.warning("killswitch.already_engaged")
            return

        self._engaged = True
        self._reason = reason
        self._engaged_at = now or datetime.now(tz=UTC)
        self._engaged_by = by

        log.critical(
            "killswitch.engaged",
            reason=reason,
            by=by,
        )

        # SR-06: yoqilish bilan yon ta'sirlarni ishga tushiramiz —
        # eng muhimi, faol capability tokenlarni bekor qilish.
        self._fire_engage_callbacks()

    def disengage(self, *, by: str = "owner") -> None:
        """Kill switch'ni o'chiradi.

        Faqat eganing aniq buyrug'i bilan.

        Raises:
            ValueError: allaqachon o'chirilgan
        """
        if not self._engaged:
            raise ValueError("Kill switch allaqachon o'chirilgan")

        log.critical(
            "killswitch.disengaged",
            was_engaged_at=str(self._engaged_at),
            was_reason=self._reason,
            by=by,
        )

        self._engaged = False
        self._reason = None
        self._engaged_at = None
        self._engaged_by = None

    def check(self) -> None:
        """Kill switch holatini tekshiradi.

        Raises:
            KillSwitchEngagedError: yoqilgan bo'lsa
        """
        if self._engaged:
            raise KillSwitchEngagedError(
                f"Emergency stop yoqilgan: {self._reason or "sabab ko'rsatilmagan"}"
            )

    @property
    def engage_callback_count(self) -> int:
        """Ro'yxatdagi callback'lar soni (test/diagnostika uchun)."""
        return len(self._engage_callbacks)

    def to_dict(self) -> dict[str, object]:
        """Holat — API va CLI uchun."""
        return {
            "engaged": self._engaged,
            "reason": self._reason,
            "engaged_at": str(self._engaged_at) if self._engaged_at else None,
            "engaged_by": self._engaged_by,
        }


async def _swallow_async_callback(coro: Awaitable[None]) -> None:
    """Fon vazifasi sifatida await qilinadigan callback — istisnolar log'ga."""
    try:
        await coro
    except Exception:
        log.warning("killswitch.async_callback_failed", exc_info=True)
