"""Executor markazlashtirilgan risk jadvalini hurmat qiladimi (audit fix).

Topilma: `Executor` approval gate'i eski `PermissionPolicy.check()`ni
chaqirardi — u FAQAT legacy `HIGH_RISK_TOOLS` frozenset'ini (6 nom)
biladi va `security/risk.py`dagi `TOOL_RISK_LEVELS` jadvalini umuman
ko'rmaydi. Natijada jadvalda HIGH deb belgilangan `telegram.channel_post`,
`github.write`, `instagram.publish_photo`, `youtube.publish`, `desktop.*`
kabi toollar WRITE ruxsat + `auto_approve_write=True` default ostida
TASDIQSIZ bajarilardi — V-32 ning "HIGH — har doim ega tasdig'i"
kafolati aynan asosiy ijro yo'lida buzilgan edi.

Bu testlar uch darajani ham asosiy yo'lda tekshiradi:
    HIGH   → har doim `ApprovalRequiredError`
    MEDIUM → default siyosatda tasdiq (fail-closed)
    LOW    → WRITE bilan avtomatik (eski xatti-harakat saqlanadi)
"""

from __future__ import annotations

from typing import Any

import pytest

from zet.core.executor import ApprovalRequiredError, Executor
from zet.domain.enums import PermissionLevel, StepStatus, TrustLevel
from zet.domain.plan import Plan, PlanStep
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import HIGH_RISK_TOOLS, PermissionPolicy
from zet.security.risk import TOOL_RISK_LEVELS, RiskLevel
from zet.tools.base import Tool
from zet.tools.registry import ToolRegistry


class _NamedTool(Tool):
    """Nomi tashqaridan beriladigan minimal tool — jadval bo'yicha risk oladi."""

    def __init__(self, name: str) -> None:
        self._name = name
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Test tool"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def _execute(self, params: dict[str, Any]) -> str:
        self.calls += 1
        return "bajarildi"


def _executor(tool: Tool, *, policy: PermissionPolicy | None = None) -> Executor:
    registry = ToolRegistry()
    registry.register(tool)
    return Executor(
        registry=registry,
        policy=policy or PermissionPolicy(),
        killswitch=KillSwitchState(),
        budget_usd=0.10,
    )


def _one_step_plan(tool_name: str, permission: PermissionLevel) -> Plan:
    return Plan(
        summary="Test reja",
        steps=[
            PlanStep(
                position=0,
                description="Amal",
                tool_name=tool_name,
                permission_required=permission,
            )
        ],
    )


class TestHighRiskTable:
    @pytest.mark.parametrize(
        "tool_name",
        ["telegram.channel_post", "github.write", "youtube.publish", "desktop.type_text"],
    )
    async def test_table_high_risk_requires_approval(self, tool_name: str) -> None:
        """Jadvaldagi HIGH tool WRITE ruxsat bilan ham tasdiqsiz o'tmaydi."""
        # Dalil: bu nomlar ESKI ro'yxatda yo'q — ya'ni test aynan yangi
        # jadval yo'lini tekshiradi, back-compat yo'lini emas.
        assert tool_name not in HIGH_RISK_TOOLS
        assert TOOL_RISK_LEVELS[tool_name] is RiskLevel.HIGH

        tool = _NamedTool(tool_name)
        executor = _executor(tool)

        with pytest.raises(ApprovalRequiredError) as exc_info:
            await executor.execute_plan(
                _one_step_plan(tool_name, PermissionLevel.WRITE),
                trust=TrustLevel.OWNER,
            )

        assert exc_info.value.step.tool_name == tool_name
        # ENG MUHIM DALIL: tool HECH QACHON bajarilmadi.
        assert tool.calls == 0

    async def test_auto_approve_write_cannot_bypass_high(self) -> None:
        """Ega `auto_approve_write` yoqsa ham HIGH chetlab o'tilmaydi (V-32)."""
        tool = _NamedTool("instagram.publish_photo")
        executor = _executor(tool, policy=PermissionPolicy(auto_approve_write=True))

        with pytest.raises(ApprovalRequiredError):
            await executor.execute_plan(
                _one_step_plan("instagram.publish_photo", PermissionLevel.WRITE),
                trust=TrustLevel.OWNER,
            )
        assert tool.calls == 0


class TestMediumRisk:
    async def test_medium_requires_approval_by_default(self) -> None:
        """MEDIUM — default fail-closed (`auto_approve_medium=False`)."""
        assert TOOL_RISK_LEVELS["note.write"] is RiskLevel.MEDIUM
        tool = _NamedTool("note.write")
        executor = _executor(tool)

        with pytest.raises(ApprovalRequiredError):
            await executor.execute_plan(
                _one_step_plan("note.write", PermissionLevel.WRITE),
                trust=TrustLevel.OWNER,
            )
        assert tool.calls == 0

    async def test_medium_auto_when_owner_enables_it(self) -> None:
        """Ega ataylab yoqsa MEDIUM avtomatik o'tadi — siyosat hurmat qilinadi."""
        tool = _NamedTool("note.write")
        executor = _executor(tool, policy=PermissionPolicy(auto_approve_medium=True))

        ctx = await executor.execute_plan(
            _one_step_plan("note.write", PermissionLevel.WRITE),
            trust=TrustLevel.OWNER,
        )

        assert ctx.results[0].status is StepStatus.DONE
        assert tool.calls == 1


class TestLowRisk:
    async def test_low_write_still_automatic(self) -> None:
        """Jadvalda yo'q tool — LOW; WRITE avtomatik (eski xatti-harakat)."""
        assert "test.plain" not in TOOL_RISK_LEVELS
        tool = _NamedTool("test.plain")
        executor = _executor(tool)

        ctx = await executor.execute_plan(
            _one_step_plan("test.plain", PermissionLevel.WRITE),
            trust=TrustLevel.OWNER,
        )

        assert ctx.results[0].status is StepStatus.DONE
        assert tool.calls == 1
