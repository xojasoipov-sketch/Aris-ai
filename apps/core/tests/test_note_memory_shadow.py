"""note.write → memory shadow ko'prigi testlari (A-03).

Obsidian vault va Postgres xotira o'zaro bog'liq bo'lishi kerak: har
note yozilganda memory'ga qisqa shadow tushishi kerak.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from zet.tools.builtin.note_write import NoteWriteTool


class _ShadowCollector:
    """`memory_shadow_fn` uchun test aldashi — chaqiruvlarni yig'adi."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, *, title: str, path: str, preview: str, tags: list[str]) -> None:
        self.calls.append({"title": title, "path": path, "preview": preview, "tags": tags})


class TestNoteMemoryShadow:
    async def test_shadow_written_on_note_create(self, tmp_path: Path) -> None:
        shadow = _ShadowCollector()
        tool = NoteWriteTool(notes_dir=tmp_path, memory_shadow_fn=shadow)

        result = await tool.execute(
            {"title": "Loyihalar/ZET g'oyasi", "content": "ZET — shaxsiy AI OS"}
        )
        assert result.success
        assert len(shadow.calls) == 1
        call = shadow.calls[0]
        assert "ZET" in call["preview"]
        assert call["tags"] == ["note"]

    async def test_shadow_includes_frontmatter_tags(self, tmp_path: Path) -> None:
        shadow = _ShadowCollector()
        tool = NoteWriteTool(notes_dir=tmp_path, memory_shadow_fn=shadow)

        await tool.execute(
            {
                "title": "Fikrlar",
                "content": "test",
                "frontmatter": {"tags": ["idea", "ai"]},
            }
        )
        assert shadow.calls[0]["tags"] == ["note", "idea", "ai"]

    async def test_shadow_failure_does_not_break_note_write(self, tmp_path: Path) -> None:
        """Fail-open: memory yiqilsa note baribir yoziladi."""

        async def _exploding_shadow(**_: Any) -> None:
            msg = "memory offline"
            raise RuntimeError(msg)

        tool = NoteWriteTool(notes_dir=tmp_path, memory_shadow_fn=_exploding_shadow)

        result = await tool.execute({"title": "Test", "content": "Hujjat matni"})
        assert result.success
        # Fayl mavjud (sync Path ishlatiladi — testda thread pool'ga o'tkazish ortiqcha)
        note_path = Path(result.output["path"])
        assert note_path.exists()  # noqa: ASYNC240 — test scope, real I/O tez
        assert "Hujjat matni" in note_path.read_text(encoding="utf-8")  # noqa: ASYNC240

    async def test_no_shadow_fn_still_works(self, tmp_path: Path) -> None:
        """Backward compat: shadow_fn berilmagan bo'lsa ham note yoziladi."""
        tool = NoteWriteTool(notes_dir=tmp_path, memory_shadow_fn=None)

        result = await tool.execute({"title": "X", "content": "y"})
        assert result.success

    async def test_shadow_preview_truncated(self, tmp_path: Path) -> None:
        """Uzun matn shadow'ga to'liq tushmasin — memory jadvali shishmasin."""
        shadow = _ShadowCollector()
        tool = NoteWriteTool(notes_dir=tmp_path, memory_shadow_fn=shadow)

        long_content = "x" * 2000
        await tool.execute({"title": "Uzun", "content": long_content})
        preview = shadow.calls[0]["preview"]
        assert len(preview) < 2000
        assert len(preview) <= 500  # `_SHADOW_PREVIEW_CHARS`


class TestDefaultRegistryWiring:
    def test_note_write_optionally_accepts_shadow_fn(self, tmp_path: Path) -> None:
        """`build_default_registry(note_memory_shadow_fn=...)` qabul qiladi."""
        from zet.tools.builtin import build_default_registry

        collector = _ShadowCollector()
        registry = build_default_registry(notes_dir=tmp_path, note_memory_shadow_fn=collector)
        assert "note.write" in registry.tool_names()

    def test_note_write_without_shadow_still_registered(self, tmp_path: Path) -> None:
        from zet.tools.builtin import build_default_registry

        registry = build_default_registry(notes_dir=tmp_path)
        assert "note.write" in registry.tool_names()


# `pytest.ini`/`pyproject` bilan asyncio auto rejim yoqilgan.
_ = pytest  # keep import
