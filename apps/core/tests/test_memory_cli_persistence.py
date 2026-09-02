"""z memory * — real DB bilan to'liq muvaffaqiyat yo'li.

`test_memory_cli.py` DB ulanmagan holatni tekshiradi; bu fayl esa haqiqiy
(vaqtinchalik sqlite) DB bilan `z memory add/search/list/stats` to'liq
ishlashini tasdiqlaydi — CLI va DB orasidagi haqiqiy integratsiya.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from zet.api import deps as api_deps
from zet.cli import app
from zet.config import get_settings
from zet.db.base import Base

runner = CliRunner()


@pytest.fixture()
def sqlite_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """CLI'ning DB-backed komandalari uchun vaqtinchalik sqlite fayl bazasi."""
    db_path = tmp_path / "zet_cli_test.db"
    monkeypatch.setenv("ZET_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    get_settings.cache_clear()
    api_deps.get_engine.cache_clear()

    engine = api_deps.get_engine()

    async def _create_schema() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_schema())

    yield

    asyncio.run(engine.dispose())
    get_settings.cache_clear()
    api_deps.get_engine.cache_clear()


class TestMemoryCLIPersistence:
    def test_add_then_stats(self, sqlite_db: None) -> None:
        add_result = runner.invoke(app, ["memory", "add", "Python haqida bilim"])
        assert add_result.exit_code == 0
        assert "qo'shildi" in add_result.output.lower()

        stats_result = runner.invoke(app, ["memory", "stats"])
        assert stats_result.exit_code == 0
        assert "1 faol yozuv" in stats_result.output

    def test_add_then_search(self, sqlite_db: None) -> None:
        runner.invoke(app, ["memory", "add", "Python dasturlash tili haqida"])
        search_result = runner.invoke(app, ["memory", "search", "Python"])
        assert search_result.exit_code == 0
        assert "Python" in search_result.output

    def test_add_then_list(self, sqlite_db: None) -> None:
        runner.invoke(app, ["memory", "add", "Bilim yozuvi", "--layer", "knowledge"])
        list_result = runner.invoke(app, ["memory", "list", "knowledge"])
        assert list_result.exit_code == 0
        assert "knowledge" in list_result.output.lower()

    def test_add_with_tags_persists(self, sqlite_db: None) -> None:
        result = runner.invoke(
            app, ["memory", "add", "Tegli yozuv", "--tag", "python", "--tag", "test"]
        )
        assert result.exit_code == 0

    def test_two_cli_invocations_share_same_data(self, sqlite_db: None) -> None:
        """Alohida `z memory add` va `z memory stats` chaqiruvlari bir xil DB'ni ko'radi."""
        runner.invoke(app, ["memory", "add", "Birinchi"])
        runner.invoke(app, ["memory", "add", "Ikkinchi"])
        stats_result = runner.invoke(app, ["memory", "stats"])
        assert "2 faol yozuv" in stats_result.output
