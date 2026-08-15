"""`PgMemoryStore.remember()` testlari — MissionEngine yozish yo'li.

Ilgari `remember()` umuman mavjud emas edi: `MissionEngine._write_memory_updates`
chaqiruvi AttributeError otar, `except Exception` uni yutib
"mission.memory_write_failed" log qilar va mission yakuni xotiraga hech
qachon yozilmasdi. Bu testlar `core/mission.py::MemoryStoreLike` protokoli
bilan aynan mos chaqiruv (positional `owner_id`, `content`; keyword-only
`layer`, `source`) haqiqiy yozuv yaratishini tekshiradi.

`conftest.py`dagi `session`/`owner` fixture'lari orqali in-memory sqlite
DB ishlatiladi (`test_pg_memory_store.py` bilan bir xil naqsh).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zet.db.models.memory import MemoryEntry as MemoryEntryRow
from zet.db.models.owner import Owner
from zet.domain.memory import MemoryLayer
from zet.memory.pg_store import PgMemoryStore


@pytest.fixture()
def store(session: AsyncSession, owner: Owner) -> PgMemoryStore:
    return PgMemoryStore(session, owner_id=owner.id)


class _FakeEmbedder:
    """Oldindan belgilangan matn->vektor xaritasi; noma'lum matn uchun `None`."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float] | None:
        self.calls.append(text)
        return self._vectors.get(text)


class _AlwaysNoneEmbedder:
    """Ollama ulanmaganini simulyatsiya qiladi — har doim `None`."""

    async def embed(self, text: str) -> list[float] | None:
        return None


class TestRemember:
    async def test_remember_creates_row(
        self, store: PgMemoryStore, session: AsyncSession, owner: Owner
    ) -> None:
        """Mission chaqiruvi bilan aynan bir xil imzo — jadvalda yozuv paydo bo'ladi."""
        mission_id = uuid.uuid4()
        await store.remember(
            owner.id,
            "Mission yakunlandi: hisobot tayyorlash",
            layer="project",
            source=f"mission:{mission_id}",
        )

        result = await session.execute(
            select(MemoryEntryRow).where(MemoryEntryRow.owner_id == owner.id)
        )
        rows = result.scalars().all()

        assert len(rows) == 1
        assert rows[0].content == "Mission yakunlandi: hisobot tayyorlash"

    async def test_remember_stores_layer_and_source(
        self, store: PgMemoryStore, session: AsyncSession, owner: Owner
    ) -> None:
        await store.remember(
            owner.id,
            "loyiha xulosasi",
            layer="project",
            source="mission:abc",
        )

        result = await session.execute(
            select(MemoryEntryRow).where(MemoryEntryRow.owner_id == owner.id)
        )
        row = result.scalars().one()

        assert row.layer == "project"
        assert row.source == "mission:abc"
        # Mission yozuvi mashina tomonidan — "system" darajasi (policy'ga mos).
        assert row.trust_level == "system"

    async def test_remember_without_embedder_persists(
        self, store: PgMemoryStore, owner: Owner
    ) -> None:
        """`embedder=None` (default) — yozuv embedding'siz baribir saqlanadi."""
        await store.remember(owner.id, "embeddersiz yozuv", layer="task", source="test")

        entries = await store.list_by_layer(MemoryLayer.TASK)
        assert len(entries) == 1
        assert entries[0].embedding is None

    async def test_remember_survives_embedder_returning_none(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        """Ollama ulanmagan bo'lsa ham (fail-open) yozuv saqlanadi, embedding'siz."""
        store = PgMemoryStore(session, owner_id=owner.id, embedder=_AlwaysNoneEmbedder())

        await store.remember(owner.id, "ulanmagan embedder", layer="project", source="mission:x")

        result = await session.execute(
            select(MemoryEntryRow).where(MemoryEntryRow.owner_id == owner.id)
        )
        row = result.scalars().one()
        assert row.content == "ulanmagan embedder"
        assert row.embedding is None

    async def test_remember_computes_embedding_when_available(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        """`add()` qayta ishlatilgani uchun embedding bir xil yo'ldan hisoblanadi."""
        embedder = _FakeEmbedder({"vektorli yozuv": [1.0, 0.0]})
        store = PgMemoryStore(session, owner_id=owner.id, embedder=embedder)

        await store.remember(owner.id, "vektorli yozuv", layer="project", source="mission:y")

        result = await session.execute(
            select(MemoryEntryRow).where(MemoryEntryRow.owner_id == owner.id)
        )
        row = result.scalars().one()
        assert row.embedding is not None
        assert row.embedding["v"] == [1.0, 0.0]
        assert embedder.calls == ["vektorli yozuv"]


class TestRememberGuards:
    async def test_remember_rejects_foreign_owner(
        self, store: PgMemoryStore, session: AsyncSession, owner: Owner
    ) -> None:
        """Boshqa eganing owner_id'si — yozuv boshqa xotiraga o'tib ketmasin."""
        with pytest.raises(ValueError, match="mos emas"):
            await store.remember(uuid.uuid4(), "begona yozuv", layer="project", source="mission:z")

        result = await session.execute(
            select(MemoryEntryRow).where(MemoryEntryRow.owner_id == owner.id)
        )
        assert result.scalars().all() == []

    async def test_remember_rejects_unknown_layer(
        self, store: PgMemoryStore, owner: Owner
    ) -> None:
        with pytest.raises(ValueError):
            await store.remember(owner.id, "noma'lum qatlam", layer="bogus", source="test")
