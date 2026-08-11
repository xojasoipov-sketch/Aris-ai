"""Bo'lim 2 — Memory CLI testlari.

Tekshiriladi:
    - z memory add — yozuv qo'shish
    - z memory search — qidirish
    - z memory list — qatlam ro'yxati
    - z memory stats — statistika
"""

from __future__ import annotations

from typer.testing import CliRunner

from zet.cli import app

runner = CliRunner()


class TestMemoryCLI:
    def test_memory_add(self) -> None:
        """z memory add — yozuv qo'shiladi."""
        result = runner.invoke(app, ["memory", "add", "Test matn"])
        assert result.exit_code == 0
        assert "qo'shildi" in result.output.lower() or "✓" in result.output

    def test_memory_add_with_layer(self) -> None:
        """z memory add --layer personal."""
        result = runner.invoke(app, ["memory", "add", "Shaxsiy matn", "--layer", "personal"])
        assert result.exit_code == 0
        assert "personal" in result.output

    def test_memory_add_with_tags(self) -> None:
        """z memory add --tag python --tag test."""
        result = runner.invoke(
            app,
            ["memory", "add", "Python kodi", "--tag", "python", "--tag", "test"],
        )
        assert result.exit_code == 0

    def test_memory_add_invalid_layer(self) -> None:
        """Noto'g'ri qatlam → xato."""
        result = runner.invoke(app, ["memory", "add", "test", "--layer", "invalid"])
        assert result.exit_code != 0

    def test_memory_stats(self) -> None:
        """z memory stats — statistika."""
        result = runner.invoke(app, ["memory", "stats"])
        assert result.exit_code == 0
        assert "xotira" in result.output.lower() or "yozuv" in result.output.lower()

    def test_memory_search_runs(self) -> None:
        """z memory search — bajariladi."""
        result = runner.invoke(app, ["memory", "search", "test"])
        assert result.exit_code == 0

    def test_memory_list_empty(self) -> None:
        """z memory list knowledge — bo'sh."""
        result = runner.invoke(app, ["memory", "list", "knowledge"])
        assert result.exit_code == 0

    def test_memory_list_invalid_layer(self) -> None:
        """z memory list invalid_layer → xato."""
        result = runner.invoke(app, ["memory", "list", "invalid"])
        assert result.exit_code != 0

    def test_memory_help(self) -> None:
        """z memory --help."""
        result = runner.invoke(app, ["memory", "--help"])
        assert result.exit_code == 0
        assert "memory" in result.output.lower()
