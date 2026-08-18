"""CapabilityDiscoveryTool (`system.capabilities`) testlari — JB-16 CASE A.

NEGA. Real ishlab chiqarish nosozligi: "Biz nimalar qilolamiz bu kanal
uchun qanday toolarimiz bor" so'ralganda hech qanday kod yo'li HAQIQIY
registry'ni tekshirmasdi. Bu testlar `build_default_registry()` orqali
yaratilgan HAQIQIY `ToolRegistry` bilan ishlaydi (mock emas) — tool
o'zi o'zini ham ro'yxatda ko'rishi (`system.capabilities` — self-
referential registration), stub/real ajratish va approval-belgisi
to'g'ri ishlashini tekshiradi.
"""

from __future__ import annotations

from pathlib import Path

from zet.tools.builtin import build_default_registry
from zet.tools.builtin.capability_discovery import CapabilityDiscoveryTool


class TestNoRegistryConnected:
    async def test_without_registry_returns_empty_honest_result(self) -> None:
        tool = CapabilityDiscoveryTool(registry=None)
        result = await tool.execute({})

        assert result.success
        assert result.output["total"] == 0
        assert "ulanmagan" in result.output["summary_text"]


class TestRealRegistry:
    async def test_lists_real_available_tools(self, tmp_path: Path) -> None:
        registry = build_default_registry(notes_dir=tmp_path)
        tool = registry.get("system.capabilities")

        result = await tool.execute({})

        assert result.success
        assert result.output["total"] > 0
        names = {t["name"] for t in result.output["available"]}
        # Har doim mavjud lokal tool — kalit/token talab qilmaydi.
        assert "time.now" in names
        assert "note.write" in names
        assert "system.capabilities" in names  # o'zini ham ko'radi

    async def test_stub_tools_marked_not_available(self, tmp_path: Path) -> None:
        """Token berilmagan — Telegram/GitHub kabi tool'lar stub, NOT_AVAILABLE."""
        registry = build_default_registry(notes_dir=tmp_path)
        tool = registry.get("system.capabilities")

        result = await tool.execute({})

        not_available_names = {t["name"] for t in result.output["not_available"]}
        assert "telegram.channel_post" in not_available_names
        assert "telegram.channel_stats" in not_available_names

    async def test_real_token_marks_telegram_available(self, tmp_path: Path) -> None:
        registry = build_default_registry(notes_dir=tmp_path, telegram_bot_token="tok")
        tool = registry.get("system.capabilities")

        result = await tool.execute({})

        available_names = {t["name"] for t in result.output["available"]}
        assert "telegram.channel_post" in available_names
        assert "telegram.channel_stats" in available_names

    async def test_channel_post_flagged_requires_approval_channel_stats_not(
        self, tmp_path: Path
    ) -> None:
        registry = build_default_registry(notes_dir=tmp_path, telegram_bot_token="tok")
        tool = registry.get("system.capabilities")

        result = await tool.execute({"topic": "telegram"})

        by_name = {t["name"]: t for t in result.output["available"]}
        assert by_name["telegram.channel_post"]["requires_approval"] is True
        assert by_name["telegram.channel_stats"]["requires_approval"] is False

    async def test_topic_filter_narrows_results(self, tmp_path: Path) -> None:
        registry = build_default_registry(notes_dir=tmp_path, telegram_bot_token="tok")
        tool = registry.get("system.capabilities")

        full = await tool.execute({})
        result = await tool.execute({"topic": "telegram"})

        all_names = {t["name"] for t in result.output["available"] + result.output["not_available"]}
        assert {
            "telegram.channel_post",
            "telegram.channel_stats",
            "telegram.delete_message",
        } <= all_names
        # Filtrlangan natija to'liq registry'dan SEZILARLI kichikroq —
        # haqiqatan toraytirilgan, hech narsa qilmagan emas.
        assert result.output["total"] < full.output["total"]
        assert "time.now" not in all_names

    async def test_unknown_topic_returns_empty_but_no_crash(self, tmp_path: Path) -> None:
        registry = build_default_registry(notes_dir=tmp_path)
        tool = registry.get("system.capabilities")

        result = await tool.execute({"topic": "qwertyzzz-yoq-narsa"})

        assert result.success
        assert result.output["total"] == 0
        assert "topilmadi" in result.output["summary_text"]

    async def test_registered_in_default_registry(self, tmp_path: Path) -> None:
        registry = build_default_registry(notes_dir=tmp_path)
        assert "system.capabilities" in registry.tool_names()

    async def test_summary_text_is_natural_and_lists_tools(self, tmp_path: Path) -> None:
        registry = build_default_registry(notes_dir=tmp_path)
        tool = registry.get("system.capabilities")

        result = await tool.execute({"topic": "time"})

        assert "time.now" in result.output["summary_text"]
