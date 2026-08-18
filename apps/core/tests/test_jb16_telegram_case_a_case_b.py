"""JB-16 — CASE A/CASE B ishlab chiqarish nosozliklarini haqiqiy komponentlar
bilan qayta hosil qilish va tuzatish testlari.

CASE A — real Telegram production crash: "Biz nimalar qilolamiz bu kanal
uchun qanday toolarimiz bor" so'ralganda `Error: 'str' object has no
attribute 'get'`. Audit (JB-16) shu error matnining PAKET ICHIDAGI YAGONA
konkret, qayta hosil qilinadigan manbaini topdi: `vision.ocr`/`video.learn`
LLM'dan JSON kutganda, top-darajadagi qiymat `dict` emasligini
tekshirmasdi (3 marta mustaqil nusxalangan `_extract_json()`). Bu fayl
o'sha aniq buzilishni HAQIQIY `VisionOcrTool`/`VideoLearnTool` orqali
qayta hosil qiladi (`test_vision_ocr.py`/`test_video_learn.py`da ham bor —
bu yerda faqat "CASE A" nomi bilan bog'liqlik hujjatlashtiriladi).

CASE B — real Telegram production bug: "Kanalning oxirgi 10 ta postini
olish" — semantik jihatdan O'QISH so'rovi — noto'g'ri HIGH-risk
`telegram.channel_post` (YOZISH tool'i) uchun tasdiq so'rovi hosil
qildi. Audit shuni aniqladi: `telegram.channel_post`/`telegram.channel_stats`
IKKALASI HAM to'liq ToolRegistry orqali Planner'ga HAR DOIM ko'rinadi
(mission-darajasidagi capability-preflight scoping bu yerga tegishli
emas — u faqat "goal"-klassifikatsiya qilingan ko'p bosqichli
missiyalarga tegishli, "kanal postini olish" kabi bitta aniq-qamrovli
so'rov "command" sifatida to'g'ridan-to'g'ri Orchestrator/Planner
yo'liga tushadi). Demak, muammo — tool REACHABILITY emas (ikkalasi ham
ko'rinadi), balki NOM O'XSHASHLIGI ("channel_post" ~ "kanal posti")
LLM'ni chalg'itishi mumkinligi. Tuzatish: ikkala tool tavsifini
(description) O'QISH/YOZISH farqini ANIQ va Planner tizim promptiga
umumiy (Telegram'ga xos bo'lmagan) nom-o'xshashligi qoidasini qo'shish
— semantik, kalit so'zlar ro'yxati EMAS.

XAVFSIZLIK REGRESSIYA KAFOLATI: bu testlar `telegram.channel_post`ning
HIGH risk/approval talabini HECH QACHON zaiflashtirmasligini haqiqiy
`PermissionPolicy`/`risk_for()` orqali tasdiqlaydi.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from zet.config import Settings
from zet.core.planner import Planner
from zet.domain.command import Intent
from zet.domain.enums import PermissionLevel, TaskClass, TrustLevel
from zet.llm.base import ToolUse
from zet.llm.fake import FakeProvider, fake_response
from zet.llm.router import ModelRouter
from zet.security.permissions import PermissionPolicy
from zet.security.risk import risk_for
from zet.tools.builtin import build_default_registry
from zet.tools.builtin.telegram_tools import TelegramChannelPostTool, TelegramChannelStatsTool


def _fixed_now() -> datetime:
    return datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)


def _make_planner(session: AsyncSession, provider: FakeProvider) -> Planner:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    router = ModelRouter(
        providers={provider.name: provider},
        session=session,
        settings=settings,
        now_fn=_fixed_now,
    )
    return Planner(router)


class TestCaseBRiskSeparationNotWeakened:
    """Real `Tool` + real `PermissionPolicy` — CASE B tuzatishi
    `telegram.channel_post`ning xavfsizligini ZAIFLASHTIRMAGANINI
    isbotlaydi, `telegram.channel_stats` esa O'QISH sifatida to'g'ri
    avtomatik ruxsat olishini."""

    def test_channel_post_risk_is_high(self) -> None:
        assert risk_for("telegram.channel_post").value == "high"

    def test_channel_stats_risk_is_low(self) -> None:
        assert risk_for("telegram.channel_stats").value == "low"

    def test_channel_post_always_requires_approval(self) -> None:
        """HIGH risk — hech qanday siyosat/avtonomiya bilan chetlab
        o'tilmaydi (V-32 kafolat) — CASE B tuzatishi buni buzmagan."""
        policy = PermissionPolicy()
        tool = TelegramChannelPostTool()
        decision = policy.requires_approval(
            permission=tool.permission_level,
            trust=TrustLevel.OWNER,
            tool=tool,
        )
        assert decision.needs_approval is True

    def test_channel_stats_never_requires_approval(self) -> None:
        """READ + LOW risk — avtomatik, tasdiqsiz (JB-16 §13: READ = no approval)."""
        policy = PermissionPolicy()
        tool = TelegramChannelStatsTool()
        decision = policy.requires_approval(
            permission=tool.permission_level,
            trust=TrustLevel.OWNER,
            tool=tool,
        )
        assert decision.needs_approval is False
        assert decision.allowed is True


class TestCaseBToolDescriptionsDisambiguateReadVsWrite:
    """Tool description'lari — Planner LLM'ga yetib boradigan YAGONA
    signal — nom o'xshashligiga qaramay operatsiyani ANIQ ajratadi."""

    def test_channel_post_description_says_write(self) -> None:
        desc = TelegramChannelPostTool().description
        assert "YOZISH" in desc
        assert "O'QIMAYDI" in desc

    def test_channel_stats_description_says_read_and_no_history(self) -> None:
        desc = TelegramChannelStatsTool().description
        assert "O'QISH" in desc
        # Bot API haqiqiy cheklovi — halol e'lon qilingan, yashirilmagan.
        assert "eski POST" in desc or "post tarixi" in desc.lower() or "metod yo'q" in desc


class TestCaseBPlannerPromptCarriesDisambiguation:
    """Real `Planner.plan()` (FakeProvider bilan, `test_planner.py`dagi
    o'rnatilgan naqsh) — tool tavsiflari HAQIQATAN LLM'ga yuboriladigan
    system promptga yetib borishini va umumiy nom-o'xshashligi
    qoidasi mavjudligini tasdiqlaydi."""

    async def test_rendered_tool_specs_include_disambiguation(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        registry = build_default_registry(notes_dir=tmp_path)
        plan_tool_use = ToolUse(
            id=f"tu_{uuid.uuid4().hex[:8]}",
            name="create_plan",
            arguments={
                "summary": "Kanal statistikasini o'qish",
                "steps": [
                    {
                        "position": 0,
                        "description": "Kanal ma'lumotini o'qish",
                        "tool_name": "telegram.channel_stats",
                        "tool_params": {"chat_id": "@mychannel"},
                        "permission_required": "read",
                        "depends_on": [],
                    }
                ],
            },
        )
        provider = FakeProvider(
            name="ollama", scripted=[fake_response(text="", tool_uses=(plan_tool_use,))]
        )
        planner = _make_planner(session, provider)

        intent = Intent(
            action="telegram.channel_stats",
            objects=["kanal"],
            task_class=TaskClass.NORMAL,
            requires_tools=["telegram.channel_stats"],
            original_text="Kanalning oxirgi postlarini ol",
        )
        plan = await planner.plan(intent, tool_specs=registry.tool_signatures())

        assert plan.steps[0].tool_name == "telegram.channel_stats"
        assert plan.steps[0].permission_required == PermissionLevel.READ

        # LLM'ga YUBORILGAN system prompt — haqiqatan disambiguatsiya
        # matnini o'z ichiga oladi (fix "yozilgan, lekin ishlatilmagan"
        # bo'lib qolmaganini isbotlaydi).
        sent_system = provider.calls[0]["system"]
        assert "O'QISH" in sent_system
        assert "YOZISH" in sent_system
        assert "NOMI so'rov so'zlariga OXSHASHLIGI" in sent_system
