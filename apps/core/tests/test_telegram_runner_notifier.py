"""Telegram runner'lari Orchestrator'ga `notifier` uzatishini qulflaydi (F1).

DALIL (bug): `get_telegram_bot()` ichidagi `_runner` va `_approval_runner`
Orchestrator'ni `notifier`siz qurardi. `Orchestrator._notify_awaiting_approval`
esa `self._notifier is None` bo'lsa jimgina chiqib ketadi — natijada Telegram
orqali boshlangan run AWAITING_APPROVAL'da to'xtaganda ega inline ✅/❌
tugmali xabarni OLMASDI, javob "(bo'sh natija)" bo'lardi.

Test usuli: `zet.api.deps.Orchestrator` monkeypatch bilan qo'lga olinadi va
konstruktor kwargs'ida `notifier` haqiqatan uzatilgani tekshiriladi — haqiqiy
Telegram (yoki LLM) chaqiruvisiz.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import zet.api.deps as deps
from zet.domain.enums import RunStatus


class _FakeRecord:
    """`Orchestrator.start()/resume()` qaytaradigan record'ning minimal stubi."""

    def __init__(self) -> None:
        self.run_id = uuid.uuid4()
        self.result_summary = "bajarildi"
        self.error: str | None = None
        self.status = RunStatus.DONE


class _FakeOrchestrator:
    """Konstruktor kwargs'ini qo'lga oluvchi stub — runner'lar wiring'ini sinaydi."""

    captured: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, **kwargs: Any) -> None:
        _FakeOrchestrator.captured.append(kwargs)

    async def start(self, command: Any) -> _FakeRecord:
        return _FakeRecord()

    def approve(self, approval_id: Any) -> _FakeRecord:
        return _FakeRecord()

    def reject(self, approval_id: Any) -> _FakeRecord:
        return _FakeRecord()

    async def resume(self, run_id: Any) -> _FakeRecord:
        return _FakeRecord()


@pytest.fixture
def telegram_bot(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> Any:
    """`get_telegram_bot()` — Orchestrator stub va in-memory DB bilan.

    `Orchestrator` deps modul globali orqali almashtiriladi (runner closure'lari
    uni chaqiruv paytida modul nomfazosidan oladi), DB esa conftest'dagi
    SQLite in-memory fabrikaga yo'naltiriladi — tarmoq/Postgres talab qilinmaydi.
    """
    _FakeOrchestrator.captured.clear()
    monkeypatch.setattr(deps, "Orchestrator", _FakeOrchestrator)
    monkeypatch.setattr(deps, "get_session_factory", lambda: session_factory)
    deps.get_telegram_bot.cache_clear()
    bot = deps.get_telegram_bot()
    yield bot
    # Boshqa testlar monkeypatch'langan muhitda qurilgan botni olmasin.
    deps.get_telegram_bot.cache_clear()


class TestTelegramRunnerNotifierWiring:
    """F1: Telegram-boshlangan run'lar ham approval xabarini olishi kerak."""

    async def test_orchestrator_runner_passes_notifier(self, telegram_bot: Any) -> None:
        """`_runner` qurgan Orchestrator `notifier` oladi (get_orchestrator bilan bir xil)."""
        runner = telegram_bot.handler._ctx.orchestrator_runner
        assert runner is not None

        result = await runner("brifing tayyorla")

        assert result.ok
        assert len(_FakeOrchestrator.captured) == 1
        kwargs = _FakeOrchestrator.captured[0]
        assert "notifier" in kwargs, (
            "F1 REGRESS: _runner Orchestrator'ga notifier uzatmayapti — "
            "Telegram run AWAITING_APPROVAL'da jim qoladi"
        )
        assert kwargs["notifier"] is not None
        # Aynan global singleton — get_orchestrator() bilan bir xil wiring.
        assert kwargs["notifier"] is deps.get_notifier()

    async def test_approval_runner_passes_notifier(
        self, telegram_bot: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`_approval_runner` ham `notifier` oladi — resume() davomida yangi
        approval paydo bo'lsa, u ham Telegram xabarini yuborishi kerak."""
        runner = telegram_bot.handler._ctx.approval_runner
        assert runner is not None

        # pending_for_run bo'sh bo'lsa runner Orchestrator qurmasdan qaytadi —
        # shuning uchun bitta soxta PENDING approval beramiz.
        fake_service = SimpleNamespace(
            pending_for_run=lambda _run_id: [SimpleNamespace(id=uuid.uuid4())]
        )
        monkeypatch.setattr(deps, "get_approval_service", lambda: fake_service)

        result = await runner("approve", str(uuid.uuid4()))

        assert result.ok
        assert len(_FakeOrchestrator.captured) == 1
        kwargs = _FakeOrchestrator.captured[0]
        assert "notifier" in kwargs, (
            "F1 REGRESS: _approval_runner Orchestrator'ga notifier uzatmayapti — "
            "resume() davomidagi yangi approval jim qoladi"
        )
        assert kwargs["notifier"] is not None
        assert kwargs["notifier"] is deps.get_notifier()
