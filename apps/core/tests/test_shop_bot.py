"""Mijoz do'kon boti testlari (Z51, #42).

NEGA BU TESTLAR BOR.

`ShopBot` — `ZetBot`ning owner-cheklovidan ATAYIN mustaqil: HAR
QANDAY yuboruvchiga javob berishi kerak (aks holda mijoz DM'i
javobsiz qoladi). Bu testlar shu xatti-harakatni qulflaydi va
`answer_fn` xato bergan holatda ham botning jim qolib
qolmasligini (fail-open) tekshiradi.
"""

from __future__ import annotations

from zet.telegram.shop_bot import ShopBot


class TestOwnerRestrictionAbsent:
    """Asosiy farq ZetBot'dan: owner tekshiruvi YO'Q."""

    async def test_responds_to_any_user_id(self) -> None:
        calls: list[int] = []

        async def answer_fn(**kwargs: object) -> str:
            calls.append(kwargs["user_id"])  # type: ignore[arg-type]
            return "javob"

        bot = ShopBot(token="t", answer_fn=answer_fn)

        # Bu user_id ZetBot uchun "begona" bo'lardi — shop bot rad etmaydi.
        reply = await bot.process_message(user_id=999_999, chat_id=1, text="salom")

        assert reply == "javob"
        assert calls == [999_999]


class TestEmptyMessage:
    async def test_empty_text_gets_greeting_without_calling_answer_fn(self) -> None:
        called = False

        async def answer_fn(**kwargs: object) -> str:
            nonlocal called
            called = True
            return "javob"

        bot = ShopBot(token="t", answer_fn=answer_fn)

        reply = await bot.process_message(user_id=1, chat_id=1, text="   ")

        assert "Salom" in reply
        assert called is False

    async def test_none_text_gets_greeting(self) -> None:
        bot = ShopBot(token="t", answer_fn=None)

        reply = await bot.process_message(user_id=1, chat_id=1, text=None)

        assert "Salom" in reply


class TestFailOpen:
    """`answer_fn` xato bersa ham bot jim qolmasligi kerak."""

    async def test_answer_fn_exception_returns_friendly_text(self) -> None:
        async def answer_fn(**kwargs: object) -> str:
            raise RuntimeError("LLM ishlamadi")

        bot = ShopBot(token="t", answer_fn=answer_fn)

        reply = await bot.process_message(user_id=1, chat_id=1, text="mahsulot bormi?")

        assert "Kechirasiz" in reply

    async def test_no_answer_fn_configured_is_honest(self) -> None:
        bot = ShopBot(token="t", answer_fn=None)

        reply = await bot.process_message(user_id=1, chat_id=1, text="salom")

        assert "ulanmagan" in reply


class TestStartStop:
    async def test_no_token_runs_in_stub_mode(self) -> None:
        bot = ShopBot(token="")

        await bot.start()

        assert bot.is_running is True
        await bot.stop()
        assert bot.is_running is False

    async def test_double_start_is_a_noop(self) -> None:
        bot = ShopBot(token="")
        await bot.start()

        await bot.start()  # ikkinchi chaqiruv xato bermasligi kerak

        assert bot.is_running is True
        await bot.stop()
