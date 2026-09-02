"""Bo'lim 2 — Memory CLI testlari.

`z memory *` endi haqiqiy DB'ga yozadi (gap-analysis #5 yopilgach — ilgari
in-memory edi). Test muhitida real Postgres/SQLite DB ulanmagan bo'lgani
uchun bu testlar CLI'ning **xato holatini** tekshiradi: ulanib bo'lmasa —
aniq xato xabari va exit_code=1 (osilib qolmaydi, jim yiqilmaydi).

To'liq CRUD oqimi `tests/test_pg_memory_store.py` (real in-memory sqlite
sessiya bilan) va `tests/test_memory_api.py::TestMemoryAPIPersistence`da
tekshiriladi.
"""

from __future__ import annotations

from typer.testing import CliRunner

from zet.cli import app

runner = CliRunner()


class TestMemoryCLI:
    def test_memory_add_reports_db_error(self) -> None:
        """DB ulanmagan holatda — aniq xato, osilib qolmaydi."""
        result = runner.invoke(app, ["memory", "add", "Test matn"])
        assert result.exit_code == 1
        assert "xotira xatosi" in result.output.lower()

    def test_memory_add_invalid_layer(self) -> None:
        """Noto'g'ri qatlam — DB'ga hech murojaat qilmasdan xato beradi."""
        result = runner.invoke(app, ["memory", "add", "test", "--layer", "invalid"])
        assert result.exit_code != 0
        assert "noto'g'ri qatlam" in result.output.lower()

    def test_memory_stats_reports_db_error(self) -> None:
        result = runner.invoke(app, ["memory", "stats"])
        assert result.exit_code == 1
        assert "xotira xatosi" in result.output.lower()

    def test_memory_search_reports_db_error(self) -> None:
        result = runner.invoke(app, ["memory", "search", "test"])
        assert result.exit_code == 1
        assert "xotira xatosi" in result.output.lower()

    def test_memory_list_reports_db_error(self) -> None:
        result = runner.invoke(app, ["memory", "list", "knowledge"])
        assert result.exit_code == 1
        assert "xotira xatosi" in result.output.lower()

    def test_memory_list_invalid_layer(self) -> None:
        """Noto'g'ri qatlam — DB'ga hech murojaat qilmasdan xato beradi."""
        result = runner.invoke(app, ["memory", "list", "invalid"])
        assert result.exit_code != 0
        assert "noto'g'ri qatlam" in result.output.lower()

    def test_memory_help(self) -> None:
        """z memory --help — DB'ga murojaat qilmaydi."""
        result = runner.invoke(app, ["memory", "--help"])
        assert result.exit_code == 0
        assert "memory" in result.output.lower()
