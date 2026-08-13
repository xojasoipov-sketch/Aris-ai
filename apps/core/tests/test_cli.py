"""Z1.15 — CLI testlari.

Typer CliRunner bilan testlash.

Tekshiriladi:
    - z version → versiya chiqishi
    - z status → jadval chiqishi
    - z budget → budjet jadvali
    - z run "msg" → qabul qilindi
    - z run --dry-run "msg" → dry-run rejimi
    - z killswitch status → holat
    - z killswitch engage → yoqildi
    - z --help → yordam
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from zet.cli import app

runner = CliRunner()


class TestCLI:
    def test_version(self) -> None:
        """z version → versiya."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "ZET" in result.output
        assert "0.1.0" in result.output

    def test_status(self) -> None:
        """z status → jadval."""
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "ZET Status" in result.output

    def test_budget(self) -> None:
        """z budget → budjet jadvali."""
        result = runner.invoke(app, ["budget"])
        assert result.exit_code == 0
        assert "Budjet" in result.output

    def test_run(self) -> None:
        """z run "msg" → qabul qilindi."""
        result = runner.invoke(app, ["run", "Havo qanday?"])
        assert result.exit_code == 0
        assert "Qabul qilindi" in result.output

    def test_run_dry_run(self) -> None:
        """z run --dry-run → dry-run rejimi."""
        result = runner.invoke(app, ["run", "--dry-run", "test"])
        assert result.exit_code == 0
        assert "dry-run" in result.output.lower()

    def test_killswitch_status(self) -> None:
        """z killswitch status → holat."""
        result = runner.invoke(app, ["killswitch", "status"])
        assert result.exit_code == 0

    def test_killswitch_engage(self) -> None:
        """z killswitch engage → yoqildi."""
        result = runner.invoke(app, ["killswitch", "engage", "--reason", "CLI test"])
        assert result.exit_code == 0
        assert "EMERGENCY" in result.output or "YOQILDI" in result.output

    def test_help(self) -> None:
        """z --help → yordam."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "ZET" in result.output


class TestDaemonCommand:
    """F9 (BLOCK-3 audit): `z daemon` to'liq wiring bilan quriladimi.

    Ilgari `DailyScheduleDaemon` `session_factory`/`llm_providers`/
    `settings`/`notifier`SIZ qurilardi — daemon "muvaffaqiyatli" ishlab,
    Telegram'ga HECH NARSA yubormasdi. Bu test aynan konstruktorga
    uzatilgan kwargs'larni ushlab, hammasi berilganini tasdiqlaydi.
    """

    def test_daemon_wires_session_factory_llm_and_notifier(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import zet.deploy.daemon as daemon_module

        captured: dict[str, object] = {}

        class _StubDaemon:
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

            async def run_forever(self) -> None:
                return None

        monkeypatch.setattr(daemon_module, "DailyScheduleDaemon", _StubDaemon)

        result = runner.invoke(app, ["daemon"])

        assert result.exit_code == 0, result.output
        # Ilgari yo'q edi — F9 fix aynan shu uchtasini qo'shdi.
        assert captured.get("session_factory") is not None, (
            "session_factory uzatilmagan — daemon real DB'ga yozolmaydi"
        )
        assert captured.get("llm_providers") is not None, (
            "llm_providers uzatilmagan — daemon FakeProvider'ga qaytadi"
        )
        assert captured.get("notifier") is not None, (
            "notifier uzatilmagan — Telegram'ga hech narsa yuborilmaydi"
        )
        assert captured.get("settings") is not None
