"""Umumiy test fixture'lari.

Unit testlar SQLite in-memory'da ishlaydi (tez, izolyatsiyalangan).
Postgres'ga xos xatti-harakat (JSONB, trigger'lar) `integration` markeri bilan
alohida sinaladi.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.testclient import TestClient

from zet.config import get_settings
from zet.db.base import Base
from zet.db.models import Conversation, Owner
from zet.db.session import create_engine, create_session_factory
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy

TEST_API_TOKEN = "test-owner-token"
"""Testlarda ishlatiladigan aniq token.

`Settings` `.env` faylini ham o'qiydi, ya'ni testlar ishlab
chiquvchining HAQIQIY `ZET_API_TOKEN`iga bog'lanib qolardi — bir
mashinada o'tib, boshqasida yiqilardi. Bu fixture uni aniq, barcha
mashinada bir xil qiymatga almashtiradi.
"""


@pytest.fixture(autouse=True)
def api_auth(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Barcha `TestClient`larga ega tokenini avtomatik qo'shadi (Z39.1).

    Token tekshiruvi middleware darajasida — ya'ni HAR bir endpoint uni
    talab qiladi. Mavjud testlar auth haqida emas, o'z mavzusi haqida;
    shuning uchun header avtomatik qo'shiladi.

    Auth'ning O'ZINI sinaydigan testlar `@pytest.mark.no_auto_auth`
    bilan bu fixture'dan chiqadi va header'ni o'zi boshqaradi.
    """
    monkeypatch.setenv("ZET_API_TOKEN", TEST_API_TOKEN)
    get_settings.cache_clear()

    if "no_auto_auth" not in request.keywords:
        original_init = TestClient.__init__

        def _init(self: TestClient, app: Any, *args: Any, **kwargs: Any) -> None:
            headers = dict(kwargs.pop("headers", None) or {})
            headers.setdefault("Authorization", f"Bearer {TEST_API_TOKEN}")
            original_init(self, app, *args, headers=headers, **kwargs)

        monkeypatch.setattr(TestClient, "__init__", _init)

    yield
    get_settings.cache_clear()


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """Har bir test uchun toza in-memory baza."""
    eng = create_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as s:
        yield s


@pytest.fixture
async def owner(session: AsyncSession) -> Owner:
    o = Owner(external_id=f"test-{uuid.uuid4().hex[:8]}", display_name="Test egasi")
    session.add(o)
    await session.commit()
    await session.refresh(o)
    return o


@pytest.fixture
async def conversation(session: AsyncSession, owner: Owner) -> Conversation:
    c = Conversation(owner_id=owner.id, channel="cli", title="Test suhbat")
    session.add(c)
    await session.commit()
    await session.refresh(c)
    return c


# ── Security fixture'lari ─────────────────────────────────────────


@pytest.fixture
def killswitch() -> KillSwitchState:
    """Yangi KillSwitchState instance."""
    return KillSwitchState()


@pytest.fixture
def permission_policy() -> PermissionPolicy:
    """Default PermissionPolicy."""
    return PermissionPolicy()
