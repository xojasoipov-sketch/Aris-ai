"""memory.write tool testlari.

Ilgari `memory.search` bor edi, `memory.write` YO'Q edi — agentlar
xotirani faqat o'qiy olardi. Bu testlar tool haqiqatan yozish
mantiqini bajarayotganini va trust_level siyosati (`memory/policy.py`)
tekshirilayotganini tasdiqlaydi.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.db.bootstrap import get_or_create_owner
from zet.db.session import session_scope
from zet.domain.memory import MemoryEntry, MemoryLayer
from zet.memory.pg_store import PgMemoryStore
from zet.tools.builtin.memory_write import MemoryWriteTool


@pytest.fixture()
def write_fn(session_factory: async_sessionmaker[AsyncSession]):
    """Test uchun haqiqiy PgMemoryStore.add()ga bog'lanadi."""

    async def _fn(
        *,
        layer: MemoryLayer,
        content: str,
        summary: str | None = None,
        tags: list[str] | None = None,
        trust_level: str = "system",
        ttl_hours: int | None = None,
    ) -> MemoryEntry:
        async with session_scope(session_factory) as session:
            owner = await get_or_create_owner(session, external_id="memwrite-tests")
            store = PgMemoryStore(session, owner_id=owner.id)
            return await store.add(
                layer=layer,
                content=content,
                summary=summary,
                tags=tags,
                trust_level=trust_level,
                now=datetime.now(UTC),
            )

    return _fn


class TestMemoryWriteTool:
    async def test_writes_to_business_layer_as_system(self, write_fn) -> None:  # type: ignore[no-untyped-def]
        """System trust — BUSINESS/PROJECT/TASK ga yozishi mumkin."""
        tool = MemoryWriteTool(write_fn=write_fn)
        result = await tool.execute(
            {
                "layer": "business",
                "content": "Mijoz Ali oyiga 5 ta buyurtma qiladi",
                "summary": "VIP mijoz — Ali",
                "tags": ["crm", "vip"],
            }
        )
        assert result.success
        assert result.output["layer"] == "business"
        assert result.output["summary"] == "VIP mijoz — Ali"

    async def test_owner_can_write_to_knowledge(self, write_fn) -> None:  # type: ignore[no-untyped-def]
        """Owner trust — KNOWLEDGE'ga yoza oladi (WRITE_POLICY)."""
        tool = MemoryWriteTool(write_fn=write_fn)
        result = await tool.execute(
            {
                "layer": "knowledge",
                "content": "Neyron tarmoqlar — asosiy tushunchalar",
                "trust_level": "owner",
            }
        )
        assert result.success
        assert result.output["layer"] == "knowledge"

    async def test_system_cannot_write_to_knowledge(self, write_fn) -> None:  # type: ignore[no-untyped-def]
        """System trust — KNOWLEDGE OWNER uchun ochiq, agent yoza olmaydi.

        Bu himoya: agent tashqi manbadan (`web.read`) olib kelgan
        'bilim' KNOWLEDGE layer'ga tushib qolmasin — ega tasdig'i kerak.
        """
        tool = MemoryWriteTool(write_fn=write_fn)
        result = await tool.execute({"layer": "knowledge", "content": "shubhali bilim"})
        assert result.success is False
        assert "system" in (result.error or "").lower()

    async def test_write_fn_not_connected(self) -> None:
        """`write_fn` berilmagan — ochiq xato (jimgina 'ok' emas)."""
        tool = MemoryWriteTool(write_fn=None)
        result = await tool.execute({"layer": "short_term", "content": "x"})
        assert result.success is False
        assert "ulanmagan" in (result.error or "").lower()

    async def test_bad_layer_returns_error(self, write_fn) -> None:  # type: ignore[no-untyped-def]
        tool = MemoryWriteTool(write_fn=write_fn)
        result = await tool.execute({"layer": "invalid_layer", "content": "x"})
        # Sxema validator layer'ni tekshiradi (enum), tool o'zi qo'shimcha
        # ToolError bermasligi mumkin — asosiysi success=False.
        assert result.success is False

    async def test_empty_content_returns_error(self, write_fn) -> None:  # type: ignore[no-untyped-def]
        tool = MemoryWriteTool(write_fn=write_fn)
        result = await tool.execute({"layer": "short_term", "content": "   "})
        assert result.success is False

    async def test_system_trust_blocked_from_owner_layer(self, write_fn) -> None:  # type: ignore[no-untyped-def]
        """WRITE_POLICY: system trust OWNER (agar mavjud) qatlamiga yoza olmaydi."""
        tool = MemoryWriteTool(write_fn=write_fn)
        result = await tool.execute({"layer": "owner", "content": "bu shaxsiy ma'lumot"})
        assert result.success is False

    async def test_untrusted_can_only_write_short_term(self, write_fn) -> None:  # type: ignore[no-untyped-def]
        """UNTRUSTED trust faqat SHORT_TERM'ga yoza oladi."""
        tool = MemoryWriteTool(write_fn=write_fn)

        # SHORT_TERM — OK
        ok_result = await tool.execute(
            {"layer": "short_term", "content": "web'dan olindi", "trust_level": "untrusted"}
        )
        assert ok_result.success

        # KNOWLEDGE — TAQIQ
        blocked = await tool.execute(
            {"layer": "knowledge", "content": "shubhali bilim", "trust_level": "untrusted"}
        )
        assert blocked.success is False


class TestRegisteredInDefaultRegistry:
    async def test_tool_available(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from zet.tools.builtin import build_default_registry

        registry = build_default_registry(notes_dir=tmp_path)
        assert "memory.write" in registry.tool_names()
