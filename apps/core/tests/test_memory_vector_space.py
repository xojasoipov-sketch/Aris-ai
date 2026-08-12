"""Vektor fazosi izolyatsiyasi testlari (Z39.2).

Eng nozik xato: `bge-m3` va `mistral-embed` IKKALASI ham 1024 o'lchamli.
Ya'ni `cosine_similarity`dagi uzunlik tekshiruvi ularni AJRATMAYDI —
taqqoslash o'tib ketadi va ma'nosiz "o'xshashlik" soni chiqadi.

Shu sabab har bir vektor yonida `model_id` saqlanadi va qidiruvda
faqat BIR XIL fazodagi vektorlar taqqoslanadi.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zet.db.models import Owner
from zet.domain.memory import MemoryLayer, MemoryQuery
from zet.memory.embeddings import EMBEDDING_MODEL_KEY
from zet.memory.pg_store import PgMemoryStore


class _Embedder:
    """Belgilangan fazoda doimiy vektor qaytaradigan soxta provayder."""

    def __init__(self, model_id: str, vector: list[float]) -> None:
        self._model_id = model_id
        self._vector = vector

    @property
    def model_id(self) -> str:
        return self._model_id

    async def embed(self, text: str) -> list[float] | None:
        return list(self._vector)

    async def aclose(self) -> None:
        return None


class TestModelTagWritten:
    """Yozuvda model belgisi saqlanadi."""

    async def test_tag_stored_next_to_vector(self, session: AsyncSession, owner: Owner) -> None:
        embedder = _Embedder("gemini:gemini-embedding-001", [0.1, 0.2])
        store = PgMemoryStore(session, owner_id=owner.id, embedder=embedder)

        entry = await store.add(layer=MemoryLayer.PERSONAL, content="salom")

        row = await store.get(entry.id)
        assert row is not None
        assert row.embedding == [0.1, 0.2]

    async def test_tag_present_in_raw_column(self, session: AsyncSession, owner: Owner) -> None:
        from zet.db.models.memory import MemoryEntry as MemoryEntryRow

        embedder = _Embedder("mistral:mistral-embed", [1.0, 0.0])
        store = PgMemoryStore(session, owner_id=owner.id, embedder=embedder)
        entry = await store.add(layer=MemoryLayer.PERSONAL, content="salom")

        import uuid as _uuid

        raw = await session.get(MemoryEntryRow, _uuid.UUID(entry.id))
        assert raw is not None
        assert raw.embedding is not None
        assert raw.embedding[EMBEDDING_MODEL_KEY] == "mistral:mistral-embed"


class TestCrossSpaceIsolation:
    """Boshqa fazodagi vektor qidiruvda taqqoslanmaydi."""

    async def test_same_dimension_different_space_is_not_compared(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        """Bir xil o'lchamli, AYNAN bir xil vektor — lekin boshqa model.

        Agar belgi ishlamasa, o'xshashlik 1.0 bo'lib ketardi.
        """
        vector = [1.0, 0.0, 0.0]

        written = PgMemoryStore(
            session,
            owner_id=owner.id,
            embedder=_Embedder("ollama:bge-m3", vector),
        )
        await written.add(layer=MemoryLayer.PERSONAL, content="mutlaqo boshqa matn")

        # Boshqa provayder bilan qidiramiz — vektor bir xil, fazo boshqa.
        searcher = PgMemoryStore(
            session,
            owner_id=owner.id,
            embedder=_Embedder("mistral:mistral-embed", vector),
        )
        results = await searcher.search(
            MemoryQuery(text="butunlay bog'liqmas so'rov", min_similarity=0.9)
        )

        assert results == []

    async def test_same_space_is_compared(self, session: AsyncSession, owner: Owner) -> None:
        """Bir xil model — vektor qidiruvi ISHLAYDI (regressiya qorovuli)."""
        vector = [1.0, 0.0, 0.0]
        embedder = _Embedder("gemini:gemini-embedding-001", vector)
        store = PgMemoryStore(session, owner_id=owner.id, embedder=embedder)

        await store.add(layer=MemoryLayer.PERSONAL, content="mutlaqo boshqa matn")

        results = await store.search(
            MemoryQuery(text="butunlay bog'liqmas so'rov", min_similarity=0.5)
        )

        assert len(results) == 1
        assert results[0].similarity > 0.5

    async def test_entry_without_embedder_still_searchable_by_keyword(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        """Vektorsiz yozuv yo'qolmaydi — kalit-so'z bilan topiladi."""
        store = PgMemoryStore(session, owner_id=owner.id)
        await store.add(layer=MemoryLayer.PERSONAL, content="Toshkentda uchrashuv")

        results = await store.search(MemoryQuery(text="Toshkentda uchrashuv"))

        assert len(results) == 1
