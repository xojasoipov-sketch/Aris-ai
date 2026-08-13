"""SR-04 + SR-06 testlari — Telegram killswitch va token bekor qilish.

SR-04 — `/killswitch` Telegram buyrug'i endi `KillSwitchState`ga
haqiqatan ulangan (avval faqat "ulanadi" degan matn qaytarardi).
SR-06 — `KillSwitchState.engage()` chaqirilganda barcha faol
capability tokenlar bekor qilinadi (aks holda emergency stop ochilgan
eshiklarni yopmasdi).

Test guruhlari:
    1. Telegram `/killswitch engage <sabab>` → runner chaqiriladi.
    2. Telegram `/killswitch disengage` → runner chaqiriladi.
    3. Non-owner user cannot engage (OwnerMiddleware fail-closed).
    4. `KillSwitchState.engage()` — callback'lar ishga tushadi.
    5. `DeviceDBRepository.revoke_all_tokens()` — barcha tokenlarga
        `revoked_at` qo'yiladi.
    6. Lifespan callback wiring — `engage()` orqali callback DB
        revokatsiyasini qanday triggerlashi.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.testclient import TestClient

from zet.api.app import create_app
from zet.api.deps import get_db_session, get_killswitch
from zet.db.bootstrap import get_or_create_owner
from zet.db.models.device import CapabilityToken as CapabilityTokenRow
from zet.db.models.device import Device as DeviceRow
from zet.devices.registry import DeviceType
from zet.devices.repository import DeviceDBRepository, _hash_token
from zet.security.killswitch import KillSwitchState
from zet.security.killswitch_actions import (
    build_killswitch_revoke_callback,
    revoke_all_capability_tokens_on_killswitch,
)
from zet.telegram.bot import ZetBot
from zet.telegram.handlers import (
    HandlerContext,
    InputType,
    KillSwitchRunResult,
    MessageHandler,
    TelegramInput,
)

# ── SR-04: Telegram `/killswitch` handler ────────────────────────────


class TestKillSwitchTelegramCommand:
    """`_handle_command`/`_handle_killswitch_command` xatti-harakati."""

    def _handler_with_runner(
        self,
    ) -> tuple[MessageHandler, list[tuple[str, str | None]], list[KillSwitchRunResult]]:
        """`killswitch_runner` chaqiruvlarini yozib boradigan handler."""
        calls: list[tuple[str, str | None]] = []
        results: list[KillSwitchRunResult] = []

        async def _runner(action: str, reason: str | None) -> KillSwitchRunResult:
            calls.append((action, reason))
            if action == "engage":
                out = KillSwitchRunResult(
                    text=f"KillSwitch yoqildi. Sabab: {reason or 'no reason'}",
                    ok=True,
                    engaged=True,
                )
            elif action == "disengage":
                out = KillSwitchRunResult(
                    text="KillSwitch o'chirildi.",
                    ok=True,
                    engaged=False,
                )
            else:
                out = KillSwitchRunResult(
                    text="KillSwitch: o'chirilgan",
                    ok=True,
                    engaged=False,
                )
            results.append(out)
            return out

        ctx = HandlerContext(killswitch_runner=_runner)
        return MessageHandler(ctx), calls, results

    @pytest.mark.asyncio()
    async def test_engage_with_reason_calls_runner(self) -> None:
        """`/killswitch engage Rack overheating` → runner engage/reason ni oladi."""
        handler, calls, _ = self._handler_with_runner()
        input_ = TelegramInput(
            input_type=InputType.COMMAND,
            user_id=123,
            chat_id=123,
            text="/killswitch engage Rack overheating",
        )
        out = await handler.handle(input_)
        assert calls == [("engage", "Rack overheating")]
        assert "yoqildi" in out.text
        # Yoqilganda 🚨 prefiksi bor
        assert "🚨" in out.text

    @pytest.mark.asyncio()
    async def test_engage_on_alias(self) -> None:
        """`/killswitch on Sabab` — `engage` sinonimi."""
        handler, calls, _ = self._handler_with_runner()
        input_ = TelegramInput(
            input_type=InputType.COMMAND,
            user_id=1,
            chat_id=1,
            text="/killswitch on Sabab",
        )
        await handler.handle(input_)
        assert calls == [("engage", "Sabab")]

    @pytest.mark.asyncio()
    async def test_disengage_calls_runner(self) -> None:
        """`/killswitch off` → runner disengage bilan chaqiriladi."""
        handler, calls, _ = self._handler_with_runner()
        input_ = TelegramInput(
            input_type=InputType.COMMAND,
            user_id=123,
            chat_id=123,
            text="/killswitch off",
        )
        out = await handler.handle(input_)
        assert calls == [("disengage", None)]
        assert "o'chirildi" in out.text

    @pytest.mark.asyncio()
    async def test_status_default(self) -> None:
        """`/killswitch` argumentsiz → status."""
        handler, calls, _ = self._handler_with_runner()
        input_ = TelegramInput(
            input_type=InputType.COMMAND,
            user_id=1,
            chat_id=1,
            text="/killswitch",
        )
        await handler.handle(input_)
        assert calls == [("status", None)]

    @pytest.mark.asyncio()
    async def test_unknown_subcommand_help(self) -> None:
        """Noto'g'ri subcommand → yordam matni, runner chaqirilmaydi."""
        handler, calls, _ = self._handler_with_runner()
        input_ = TelegramInput(
            input_type=InputType.COMMAND,
            user_id=1,
            chat_id=1,
            text="/killswitch bogus",
        )
        out = await handler.handle(input_)
        assert calls == []
        assert "Noma'lum killswitch amali" in out.text

    @pytest.mark.asyncio()
    async def test_runner_none_returns_stub(self) -> None:
        """`killswitch_runner=None` — eski stub matnini qaytaradi (back-compat)."""
        ctx = HandlerContext()  # runner yo'q
        handler = MessageHandler(ctx)
        input_ = TelegramInput(
            input_type=InputType.COMMAND,
            user_id=1,
            chat_id=1,
            text="/killswitch on Test",
        )
        out = await handler.handle(input_)
        assert "KillSwitch boshqaruvi" in out.text
        assert "Bo'lim 7" in out.text

    @pytest.mark.asyncio()
    async def test_runner_exception_shows_error(self) -> None:
        """Runner istisno tashlaganda handler xato matnini qaytaradi."""

        async def _boom(action: str, reason: str | None) -> KillSwitchRunResult:
            raise RuntimeError("db down")

        ctx = HandlerContext(killswitch_runner=_boom)
        handler = MessageHandler(ctx)
        input_ = TelegramInput(
            input_type=InputType.COMMAND,
            user_id=1,
            chat_id=1,
            text="/killswitch engage",
        )
        out = await handler.handle(input_)
        assert "❌" in out.text
        assert "db down" in out.text


# ── SR-04: Owner middleware bloklaydi ────────────────────────────────


class TestKillSwitchOwnerGate:
    """Bot darajasi — `OwnerMiddleware` non-owner ni to'sib qo'yadi."""

    @pytest.mark.asyncio()
    async def test_non_owner_cannot_engage(self) -> None:
        """Ro'yxatdan tashqari user_id → `process_message` None, runner chaqirilmaydi.

        `OwnerMiddleware` (A-05, R-04) `ZetBot.process_message`da eng
        birinchi qatlam. Non-owner uchun `killswitch_runner` HECH QACHON
        chaqirilmaydi — tokenlar bekor qilinmaydi, `KillSwitchState`
        o'zgarmaydi. Bu SR-04 xavfsizlik shartining fundamental
        himoya to'sig'i.
        """
        called: list[tuple[str, str | None]] = []

        async def _runner(action: str, reason: str | None) -> KillSwitchRunResult:
            called.append((action, reason))
            return KillSwitchRunResult(text="engaged", ok=True, engaged=True)

        bot = ZetBot(
            owner_ids={999},
            killswitch_runner=_runner,
        )

        result = await bot.process_message(
            user_id=42,  # ro'yxatda yo'q
            chat_id=42,
            text="/killswitch engage Attack",
        )
        assert result is None
        assert called == []

    @pytest.mark.asyncio()
    async def test_owner_engage_reaches_runner(self) -> None:
        """Ro'yxatdagi user → runner engage/reason bilan chaqiriladi."""
        calls: list[tuple[str, str | None]] = []

        async def _runner(action: str, reason: str | None) -> KillSwitchRunResult:
            calls.append((action, reason))
            return KillSwitchRunResult(text="ok", ok=True, engaged=True)

        bot = ZetBot(owner_ids={42}, killswitch_runner=_runner)
        result = await bot.process_message(
            user_id=42,
            chat_id=42,
            text="/killswitch engage Overheating",
        )
        assert result is not None
        assert calls == [("engage", "Overheating")]


# ── SR-06: `KillSwitchState` callback mexanizmi ──────────────────────


class TestKillSwitchCallbacks:
    def test_engage_triggers_sync_callback(self) -> None:
        """Sinxron callback `engage()`da chaqiriladi."""
        ks = KillSwitchState()
        fired: list[int] = []
        ks.register_engage_callback(lambda: fired.append(1))

        ks.engage(reason="Test")
        assert fired == [1]

    def test_multiple_callbacks_all_fire(self) -> None:
        """Bir nechta callback ro'yxatga olinsa, hammasi chaqiriladi."""
        ks = KillSwitchState()
        seen: list[str] = []
        ks.register_engage_callback(lambda: seen.append("a"))
        ks.register_engage_callback(lambda: seen.append("b"))

        ks.engage(reason="Test")
        assert seen == ["a", "b"]

    def test_callback_exception_does_not_block_engage(self) -> None:
        """Callback istisno bersa `engage()` baribir yakunlanadi (fail-open)."""
        ks = KillSwitchState()

        def _boom() -> None:
            raise RuntimeError("nope")

        fired_after: list[int] = []
        ks.register_engage_callback(_boom)
        ks.register_engage_callback(lambda: fired_after.append(1))

        ks.engage(reason="Test")
        # Bayroq baribir yoqilgan
        assert ks.is_engaged is True
        # Ikkinchi callback ham chaqirilgan (birinchi istisnosi to'smagan)
        assert fired_after == [1]

    def test_second_engage_idempotent_no_recall(self) -> None:
        """Idempotent engage — ikkinchi chaqiriq callback'ni qayta ishga tushirmaydi."""
        ks = KillSwitchState()
        fired: list[int] = []
        ks.register_engage_callback(lambda: fired.append(1))

        ks.engage(reason="First")
        ks.engage(reason="Second")  # idempotent, sabab birinchisi
        assert fired == [1]
        assert ks.reason == "First"

    @pytest.mark.asyncio()
    async def test_async_callback_scheduled_as_task(self) -> None:
        """Async callback — event loop mavjud bo'lganda fon vazifasi."""
        ks = KillSwitchState()
        fired = 0

        async def _cb() -> None:
            nonlocal fired
            fired += 1

        ks.register_engage_callback(_cb)
        ks.engage(reason="Test")
        # `create_task` faqat rejalashtiradi — biroz yield qilamiz.
        import asyncio

        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert fired == 1

    def test_clear_engage_callbacks(self) -> None:
        """`clear_engage_callbacks` ro'yxatni bo'shatadi (test yordamchisi)."""
        ks = KillSwitchState()
        ks.register_engage_callback(lambda: None)
        assert ks.engage_callback_count == 1
        ks.clear_engage_callbacks()
        assert ks.engage_callback_count == 0


# ── SR-06: `DeviceDBRepository.revoke_all_tokens` ────────────────────


class TestRevokeAllTokens:
    @pytest.mark.asyncio()
    async def test_revoke_all_marks_active_tokens(self, session: AsyncSession) -> None:
        """Registratsiya qilingan qurilmalar tokenlari `revoked_at` bilan yopiladi."""
        owner = await get_or_create_owner(session, external_id="ks-test")
        repo = DeviceDBRepository(session, owner_id=owner.id)

        _, raw1 = await repo.register(
            name="Phone", device_type=DeviceType.PHONE, capabilities=["notify"]
        )
        _, raw2 = await repo.register(
            name="Camera", device_type=DeviceType.CAMERA, capabilities=["camera.snapshot"]
        )
        _, raw3 = await repo.register(
            name="Mac", device_type=DeviceType.DESKTOP, capabilities=["notify"]
        )
        # Uchtasi ham valid.
        assert await repo.validate_token(raw1, "notify") is True
        assert await repo.validate_token(raw2, "camera.snapshot") is True
        assert await repo.validate_token(raw3, "notify") is True

        count = await repo.revoke_all_tokens()
        assert count == 3

        # Hammasi `validate_token` rad etadi.
        assert await repo.validate_token(raw1, "notify") is False
        assert await repo.validate_token(raw2, "camera.snapshot") is False
        assert await repo.validate_token(raw3, "notify") is False

    @pytest.mark.asyncio()
    async def test_revoke_all_preserves_already_revoked(self, session: AsyncSession) -> None:
        """Oldindan bekor qilingan token `revoked_at` sanasi o'zgarmaydi."""
        owner = await get_or_create_owner(session, external_id="ks-test-2")
        repo = DeviceDBRepository(session, owner_id=owner.id)

        _, raw_active = await repo.register(
            name="Phone", device_type=DeviceType.PHONE, capabilities=["notify"]
        )
        _, raw_pre = await repo.register(
            name="Old", device_type=DeviceType.PHONE, capabilities=["notify"]
        )
        # Bittasini oldindan bekor qilamiz.
        pre_time = datetime.now(UTC) - timedelta(days=1)
        row_pre = (
            await session.execute(
                select(CapabilityTokenRow).where(
                    CapabilityTokenRow.token_hash == _hash_token(raw_pre)
                )
            )
        ).scalar_one()
        row_pre.revoked_at = pre_time
        await session.flush()

        count = await repo.revoke_all_tokens()
        assert count == 1  # faqat faol bittasi

        # Oldingi bekor qilinganning vaqti o'zgarmagan.
        await session.refresh(row_pre)
        assert row_pre.revoked_at is not None
        assert abs((row_pre.revoked_at - pre_time).total_seconds()) < 1

        # Faol bo'lgani endi rad etiladi.
        assert await repo.validate_token(raw_active, "notify") is False

    @pytest.mark.asyncio()
    async def test_revoke_all_scoped_to_owner(self, session: AsyncSession) -> None:
        """Bir egaga tegishli chaqiruv boshqa egasi tokenlarini tegmaydi."""
        owner_a = await get_or_create_owner(session, external_id="ks-owner-a")
        owner_b = await get_or_create_owner(session, external_id="ks-owner-b")
        repo_a = DeviceDBRepository(session, owner_id=owner_a.id)
        repo_b = DeviceDBRepository(session, owner_id=owner_b.id)

        _, raw_a = await repo_a.register(
            name="A-Phone", device_type=DeviceType.PHONE, capabilities=["notify"]
        )
        _, raw_b = await repo_b.register(
            name="B-Phone", device_type=DeviceType.PHONE, capabilities=["notify"]
        )

        count_a = await repo_a.revoke_all_tokens()
        assert count_a == 1
        assert await repo_a.validate_token(raw_a, "notify") is False
        # B egasining tokeni tegilmagan.
        assert await repo_b.validate_token(raw_b, "notify") is True

    @pytest.mark.asyncio()
    async def test_revoke_all_empty_returns_zero(self, session: AsyncSession) -> None:
        """Hech token bo'lmasa — 0 qaytaradi, xato bermaydi."""
        owner = await get_or_create_owner(session, external_id="ks-empty")
        repo = DeviceDBRepository(session, owner_id=owner.id)
        assert await repo.revoke_all_tokens() == 0


# ── SR-06: `revoke_all_capability_tokens_on_killswitch` (global) ─────


class TestGlobalRevokeHelper:
    @pytest.mark.asyncio()
    async def test_global_helper_revokes_across_owners(
        self, session_factory: async_sessionmaker[AsyncSession], session: AsyncSession
    ) -> None:
        """Killswitch — global miqyos, barcha egalarning tokenlarini yopadi."""
        owner_a = await get_or_create_owner(session, external_id="ks-global-a")
        owner_b = await get_or_create_owner(session, external_id="ks-global-b")
        await DeviceDBRepository(session, owner_id=owner_a.id).register(
            name="A", device_type=DeviceType.PHONE, capabilities=["notify"]
        )
        await DeviceDBRepository(session, owner_id=owner_b.id).register(
            name="B", device_type=DeviceType.PHONE, capabilities=["notify"]
        )
        await session.commit()

        count = await revoke_all_capability_tokens_on_killswitch(session_factory)
        assert count == 2

        async with session_factory() as check:
            rows = (await check.execute(select(CapabilityTokenRow))).scalars().all()
            assert len(rows) == 2
            assert all(r.revoked_at is not None for r in rows)

    @pytest.mark.asyncio()
    async def test_fail_open_on_broken_factory(self) -> None:
        """Xatoli factory — 0 qaytariladi, istisno tashlanmaydi (fail-open)."""

        class _Broken:
            def __call__(self) -> Any:
                raise RuntimeError("db exploded")

        count = await revoke_all_capability_tokens_on_killswitch(_Broken())  # type: ignore[arg-type]
        assert count == 0


# ── SR-06: lifespan wiring — `engage()` orqali callback DB'ga yetadi ─


class TestLifespanCallbackWiring:
    @pytest.mark.asyncio()
    async def test_callback_triggers_bulk_revoke_via_engage(
        self, session_factory: async_sessionmaker[AsyncSession], session: AsyncSession
    ) -> None:
        """`register_engage_callback` + `engage()` — DB'da tokenlar yopiladi.

        Bu integratsion test lifespan bilan bir xil zanjirni imitasiya
        qiladi: singleton `KillSwitchState`ga callback ro'yxatga olinadi,
        keyin `engage()` chaqiriladi va async task loop yieldida
        yugurib DB'ni yangilaydi.
        """
        # Tokenlarni tayyorlaymiz.
        owner = await get_or_create_owner(session, external_id="ks-wire-owner")
        _, raw = await DeviceDBRepository(session, owner_id=owner.id).register(
            name="Phone", device_type=DeviceType.PHONE, capabilities=["notify"]
        )
        await session.commit()

        # Yangi ks va callback — singleton bilan aralashmasin.
        ks = KillSwitchState()
        ks.register_engage_callback(build_killswitch_revoke_callback(session_factory))

        ks.engage(reason="Bulk revoke wiring test")
        # Callback async — loop yieldida ishga tushadi. Task tugashini
        # kutish uchun `asyncio.all_tasks` orqali topamiz.
        pending = [t for t in asyncio.all_tasks() if not t.done()]
        pending = [t for t in pending if t is not asyncio.current_task()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        # DB'da token endi bekor qilingan.
        async with session_factory() as check:
            device_ids = select(DeviceRow.id).where(DeviceRow.owner_id == owner.id)
            row = (
                await check.execute(
                    select(CapabilityTokenRow).where(CapabilityTokenRow.device_id.in_(device_ids))
                )
            ).scalar_one()
            assert row.revoked_at is not None

        # Va `validate_token` endi rad etadi.
        async with session_factory() as check2:
            repo = DeviceDBRepository(check2, owner_id=owner.id)
            assert await repo.validate_token(raw, "notify") is False


# ── REST integratsion — engage endpoint tokenlarni bekor qiladi ──────


class TestRestKillSwitchRevokes:
    """`POST /api/v1/killswitch/engage` — SR-06 uchidan-uchgacha."""

    @pytest.fixture()
    def client(self, session: AsyncSession) -> TestClient:
        app = create_app()

        async def _session_override():
            yield session

        # Killswitch singletonini toza instance bilan almashtiramiz —
        # boshqa testlar bilan aralashmasin.
        fresh_ks = KillSwitchState()
        app.dependency_overrides[get_db_session] = _session_override
        app.dependency_overrides[get_killswitch] = lambda: fresh_ks
        return TestClient(app, raise_server_exceptions=False)

    def test_engage_endpoint_returns_revoked_count(self, client: TestClient) -> None:
        """Endpoint javobida `revoked_token_count` mavjud (fail-open holda 0)."""
        resp = client.post("/api/v1/killswitch/engage", json={"reason": "REST test"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "engaged"
        # `revoked_token_count` maydoni doim bo'ladi (DB yetib bo'lmasa 0).
        assert "revoked_token_count" in body
        assert isinstance(body["revoked_token_count"], int)
