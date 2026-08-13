"""Mijoz do'kon boti — DM orqali savol-javob (Z51, #42).

NEGA ALOHIDA BOT.

`ZetBot` `OwnerMiddleware` bilan FAIL-CLOSED qurilgan (V-17, A-05,
R-04): faqat ega yozganda javob beradi, boshqa yuboruvchining xabari
jimgina o'tkazib yuboriladi (`middleware.py::check`,
`polling.py::_handle_message`). Bu mijoz xizmatiga tamomila
YAROQSIZ — mijoz aynan "ega emas" bo'lgani uchun ZetBot uni butunlay
e'tiborsiz qoldiradi.

Lekin ZetBot'ni "kengaytirish" (owner tekshiruvini olib tashlash) ham
noto'g'ri yechim: uning ortida to'liq `Orchestrator` turadi — fayl
o'qish, terminal, email, hatto Telegram xabar yuborish kabi EXECUTE
darajali tool'lar bilan. Begona odam yozgan matn LLM orqali tool
chaqiruviga aylanishi mumkin (prompt injection) — bu yerda xato narxi
juda yuqori: mijoz ega kompyuterida buyruq bajarilishiga olib
kelishi mumkin.

Shu sabab `ShopBot` TUBDAN TORROQ:
    1. Owner tekshiruvi YO'Q — ataylab, HAR KIMGA javob beradi.
    2. Hech qanday tool YO'Q. Javob ikki bosqichda tuziladi:
       a) `CommerceRepository.search_products()` — oddiy LIKE
          qidiruv (LLM emas, deterministik — mahsulot narxini LLM
          "o'ylab topmaydi", faqat bazadagi haqiqiy qatordan oladi).
       b) Bitta LLM `complete()` chaqiruvi — TOOLSIZ (`tools=()`),
          faqat topilgan mahsulotlar asosida tabiiy javob yozish
          uchun. Modelga hech qanday funksiya taqdim etilmagani
          uchun tool-chaqiruv xavfi mavjud emas.

Har bir DM yozgan odam CRM kontaktga aylanadi
(`get_or_create_contact_by_chat_id`) — keyinchalik shu kontakt
`Order.contact_id`ga bog'lanadi va #43 (kargo chiqishi xabari) shu
orqali mijozni topadi.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from zet.telegram.shop_polling import ShopBotPoller

log = structlog.get_logger(__name__)

AnswerFn = Callable[..., Awaitable[str]]
"""`(*, chat_id, user_id, text, username, display_name) -> javob matni`.

Chaqiruvchi (`deps.py`) o'z DB sessiyasini shu funksiya ICHIDA ochadi —
`ShopBot`ning o'zi DB'ni bilmaydi, xuddi `ZetBot.orchestrator_runner`
kabi."""


class ShopBot:
    """Mijoz do'kon boti — faqat matn, faqat READ, tool'siz (Z51)."""

    def __init__(self, *, token: str = "", answer_fn: AnswerFn | None = None) -> None:
        self._token = token
        self._answer_fn = answer_fn
        self._running = False
        self._poller: ShopBotPoller | None = None
        self._poller_task: asyncio.Task[None] | None = None
        log.info("shop_bot.init", has_token=bool(token))

    @property
    def is_running(self) -> bool:
        return self._running

    async def process_message(
        self,
        *,
        user_id: int,
        chat_id: int,
        text: str | None,
        username: str = "",
        display_name: str = "",
    ) -> str:
        """HAR QANDAY yuboruvchiga javob qaytaradi — owner tekshiruvi YO'Q (ataylab)."""
        stripped = (text or "").strip()
        if not stripped:
            return "Salom! Mahsulot haqida savolingizni yozing — yordam beraman."
        if self._answer_fn is None:
            log.warning("shop_bot.no_answer_fn")
            return "Hozircha javob bera olmayman — savdo bo'limi ulanmagan."
        try:
            return await self._answer_fn(
                chat_id=chat_id,
                user_id=user_id,
                text=stripped,
                username=username,
                display_name=display_name,
            )
        except Exception:
            log.exception("shop_bot.answer_failed", chat_id=chat_id)
            return "Kechirasiz, hozir javob bera olmadim — birozdan so'ng qayta yozing."

    async def start(self) -> None:
        """Botni ishga tushirish — token bo'lsa haqiqiy long-polling."""
        if self._running:
            log.warning("shop_bot.already_running")
            return

        if not self._token:
            log.warning("shop_bot.no_token", msg="Token berilmagan — stub rejimda ishlaydi")
            self._running = True
            log.info("shop_bot.started", mode="stub")
            return

        from zet.telegram.shop_polling import ShopBotPoller

        self._poller = ShopBotPoller(token=self._token, bot=self)
        self._poller_task = asyncio.create_task(self._poller.run_forever())
        self._running = True
        log.info("shop_bot.started", mode="polling")

    async def stop(self) -> None:
        """Botni to'xtatish — polling loopini yopadi va HTTP klientni tozalaydi."""
        if not self._running:
            return

        if self._poller is not None:
            self._poller.stop()
        if self._poller_task is not None:
            self._poller_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._poller_task
        if self._poller is not None:
            await self._poller.aclose()

        self._running = False
        log.info("shop_bot.stopped")


__all__ = ["AnswerFn", "ShopBot"]
