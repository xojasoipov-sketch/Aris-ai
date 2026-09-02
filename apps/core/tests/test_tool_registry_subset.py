"""`ToolRegistry.subset()` testlari (JB-4).

Audit topilmasi: Mission bundle qanday tool tanlagan bo'lsa ham, ijro
HAR DOIM to'liq global registry orqali borardi — tanlov ko'rsatma edi,
CHEGARA emas. `subset()` — cheklovni haqiqiy qiladigan mexanizm:
qaytgan registry FAQAT berilgan nomlarni ko'radi.
"""

from __future__ import annotations

from typing import Any

import pytest

from zet.tools.base import Tool
from zet.tools.registry import ToolNotFoundError, ToolRegistry


class _StubTool(Tool):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "stub"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def _execute(self, params: dict[str, Any]) -> str:
        return "ok"


def _registry(*names: str) -> ToolRegistry:
    reg = ToolRegistry()
    for n in names:
        reg.register(_StubTool(n))
    return reg


class TestSubset:
    def test_subset_only_contains_requested_tools(self) -> None:
        full = _registry("web.search", "note.write", "shell.exec")

        scoped = full.subset(["web.search", "note.write"])

        assert sorted(scoped.tool_names()) == ["note.write", "web.search"]
        assert not scoped.has("shell.exec")

    def test_subset_get_raises_for_excluded_tool(self) -> None:
        """ENG MUHIM DALIL: chegara faqat ko'rsatma emas — HAQIQIY to'siq.

        LLM hallyutsinatsiya qilib chetdagi tool nomini bersa ham,
        Executor bu registrydan uni topolmasligi kerak.
        """
        full = _registry("web.search", "shell.exec")

        scoped = full.subset(["web.search"])

        with pytest.raises(ToolNotFoundError):
            scoped.get("shell.exec")

    def test_included_tool_is_fully_usable(self) -> None:
        full = _registry("web.search", "shell.exec")
        scoped = full.subset(["web.search"])

        tool = scoped.get("web.search")

        assert tool.name == "web.search"

    def test_unknown_names_are_silently_dropped(self) -> None:
        """Fail-open: chaqiruvchi ro'yxati allaqachon tekshirilgan deb hisoblanadi."""
        full = _registry("web.search")

        scoped = full.subset(["web.search", "ghost.tool"])

        assert scoped.tool_names() == ["web.search"]

    def test_empty_names_produces_empty_registry(self) -> None:
        full = _registry("web.search")

        scoped = full.subset([])

        assert scoped.tool_names() == []

    def test_subset_does_not_mutate_original(self) -> None:
        full = _registry("web.search", "shell.exec")

        full.subset(["web.search"])

        assert sorted(full.tool_names()) == ["shell.exec", "web.search"]

    def test_tool_signatures_also_scoped(self) -> None:
        """Planner ko'radigan imzolar ham cheklangan — nafaqat execute()."""
        full = _registry("web.search", "shell.exec")
        scoped = full.subset(["web.search"])

        names = {sig.name for sig in scoped.tool_signatures()}

        assert names == {"web.search"}
