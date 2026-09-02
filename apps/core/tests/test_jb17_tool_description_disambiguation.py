"""JB-17 — tool-tanlash farosati auditi: O'QISH/YOZISH aniqligi (Bo'lim 2).

NEGA. JB-16 Telegram bug'idan keyingi audit boshqa tool'larda ham xuddi
shu naqshni topdi: nom bitta operatsiyani (masalan "status", "post",
"media") anglatishi mumkin, lekin tavsif buni tasdiqlash/rad etishni
ANIQ qilmasa, LLM Planner (faqat `ToolSignature.render()` orqali
nom+tavsifni ko'radi — permission_level/risk_level'ni KO'RMAYDI)
noto'g'ri tool tanlashi mumkin. Bu testlar har bir tuzatilgan tool
tavsifida O'QISH/YOZISH signali va (kerak bo'lsa) qarshi tool'ga
ishorani QOTIRADI — regressiyada yo'qolib qolmasin.
"""

from __future__ import annotations

from pathlib import Path

from zet.tools.builtin.commerce_tools import OrdersListTool, OrderStatusUpdateTool
from zet.tools.builtin.deploy_push import DeployPushTool
from zet.tools.builtin.github import GitHubReadTool, GitHubWriteTool
from zet.tools.builtin.instagram import InstagramRecentMediaTool
from zet.tools.builtin.workspace_tools import TaskUpdateTool


class TestGithubReadWriteDisambiguation:
    def test_read_says_read_and_no_comments(self) -> None:
        desc = GitHubReadTool().description
        assert "O'QISH" in desc
        assert "IZOHLARINI" in desc

    def test_write_says_write_and_not_read(self) -> None:
        desc = GitHubWriteTool().description
        assert "YOZISH" in desc
        assert "O'QISH uchun EMAS" in desc


class TestOrderReadWriteDisambiguation:
    def test_set_status_says_write_despite_name(self) -> None:
        desc = OrderStatusUpdateTool().description
        assert "YOZISH" in desc
        assert "order.list" in desc

    def test_list_says_read_and_points_away_from_set_status(self) -> None:
        desc = OrdersListTool().description
        assert "O'QISH" in desc
        assert "order.set_status" in desc


class TestTaskUpdateDisambiguation:
    def test_update_points_to_create(self) -> None:
        desc = TaskUpdateTool().description
        assert "YOZISH" in desc
        assert "task.create" in desc


class TestInstagramRecentMediaDisambiguation:
    def test_recent_media_says_read_not_publish(self) -> None:
        desc = InstagramRecentMediaTool().description
        assert "O'QISH" in desc
        assert "instagram.publish_photo" in desc


class TestDeployPushDisambiguation:
    def test_deploy_push_disclaims_real_hosting(self) -> None:
        desc = DeployPushTool(sites_dir=Path("sites")).description
        assert "YOZISH" in desc
        assert "git/hosting push emas" in desc


class TestPlannerSystemFamilyRule:
    """PLANNER_SYSTEM'dagi 2b qoidasi — resurs-oilasida o'qish tool'i
    umuman yo'qligini tekshirish talabi mavjudligini qotiradi."""

    def test_rule_2b_present(self) -> None:
        from zet.prompts.planner import PLANNER_SYSTEM

        assert "2b." in PLANNER_SYSTEM
        assert "RO'YXAT/QIDIRUV" in PLANNER_SYSTEM


class TestPlannerSystemMemoryPromotionRule:
    """PLANNER_SYSTEM'dagi 'muhim faktlarni eslab qolish' yo'riqnomasi —
    xotira/kontekst auditi topilmasi tuzatishi (Bo'lim 4)."""

    def test_memory_promotion_guidance_present(self) -> None:
        from zet.prompts.planner import PLANNER_SYSTEM

        assert "MUHIM FAKTLARNI ESLAB QOLISH" in PLANNER_SYSTEM
        assert "memory.write" in PLANNER_SYSTEM
        assert 'layer="conversation"' in PLANNER_SYSTEM
