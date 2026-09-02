"""Risk-based approval testlari (V-32 kengaytmasi + AUTONOMY_AUDIT §2.8).

NEGA: risk axis PermissionLevel'dan alohida ish qiladi — WRITE tool
`note.write` xususiy vault'ga (LOW) va `github.write` jamoat repo'ga
(HIGH) ikkalasi ham WRITE, lekin approval oqimi butunlay boshqa. Bu
test to'plami quyidagilarni tekshiradi:

    1. Tool.risk_level default = LOW, subclass override yechim
    2. TOOL_RISK_LEVELS jadvali HIGH/MEDIUM ni to'g'ri belgilagan
    3. PermissionPolicy.requires_approval() ikki o'qni birlashtiradi
    4. HIGH ni hech qanday siyosat/autonomy bekor qilolmaydi (V-32)
    5. MEDIUM sozlanadigan + autonomy shartga bog'liq
    6. AutonomyLevel.L5_MONITORED + CONTINUOUS_MONITORING
    7. ApprovalRequest risk_level'ni tashiy oladi
"""

from __future__ import annotations

import uuid
from typing import Any

from zet.automation.autonomy import (
    AutonomyCapability,
    AutonomyLevel,
    allows,
    policy_for,
)
from zet.domain.enums import PermissionLevel, RiskLevel, TrustLevel
from zet.security.approvals import ApprovalService
from zet.security.permissions import PermissionPolicy
from zet.security.risk import TOOL_RISK_LEVELS
from zet.tools.base import Tool


class _StubTool(Tool):
    """Minimal Tool subclass — risk_level default sinov uchun."""

    def __init__(
        self,
        *,
        name: str = "stub.demo",
        risk: RiskLevel | None = None,
    ) -> None:
        self._name = name
        self._risk_override = risk

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:  # pragma: no cover — sinovlar chaqirmaydi
        return "stub"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def risk_level(self) -> RiskLevel:
        if self._risk_override is not None:
            return self._risk_override
        return super().risk_level

    async def _execute(self, params: dict[str, Any]) -> Any:  # pragma: no cover
        return None


class TestT1ToolRiskDefault:
    """T1: risk_level defaulti — noma'lum tool nomi bo'lsa LOW."""

    def test_bare_tool_defaults_to_low(self) -> None:
        tool = _StubTool(name="never.registered.stub")
        assert tool.risk_level is RiskLevel.LOW

    def test_time_now_is_low_by_table(self) -> None:
        """`time.now` — jadvalda yo'q, demak default LOW."""
        tool = _StubTool(name="time.now")
        # Jadval faqat HIGH/MEDIUM'ni sanaydi; LOW default
        assert tool.risk_level is RiskLevel.LOW


class TestT2ClassificationTableHigh:
    """T2: jadval ma'lum HIGH toollarni belgilagan."""

    def test_high_risk_entries(self) -> None:
        expected = [
            "shell.exec",
            "github.write",
            "telegram.channel_post",
            "instagram.publish_photo",
            "youtube.publish",
            "file.delete",
            "agent.disable",
        ]
        for name in expected:
            assert TOOL_RISK_LEVELS[name] is RiskLevel.HIGH, name

    def test_desktop_ui_inputs_are_high(self) -> None:
        for name in ("desktop.type_text", "desktop.key_press", "desktop.mouse_click"):
            assert TOOL_RISK_LEVELS[name] is RiskLevel.HIGH, name


class TestT3ClassificationTableMedium:
    """T3: business writes jadvalda MEDIUM."""

    def test_medium_risk_entries(self) -> None:
        expected = [
            "order.set_status",
            "task.create",
            "project.create",
            "crm.contact_create",
            "note.write",
            "memory.write",
            # F8 (BLOCK-3 audit): lokal fayl generatsiya, real hosting yo'q.
            "deploy.push",
        ]
        for name in expected:
            assert TOOL_RISK_LEVELS[name] is RiskLevel.MEDIUM, name


class TestT4HighRiskAlwaysApproves:
    """T4: HIGH — hatto eng ochiq siyosat va autonomy'da ham tasdiq."""

    def test_high_risk_wins_over_permissive_policy(self) -> None:
        policy = PermissionPolicy(auto_approve_write=True, auto_approve_medium=True)
        decision = policy.requires_approval(
            tool_name="github.write",
            permission=PermissionLevel.WRITE,
            trust=TrustLevel.SYSTEM,
            risk=RiskLevel.HIGH,
            autonomy_level=AutonomyLevel.L4_AUTONOMOUS,
        )
        assert decision.allowed is False
        assert decision.needs_approval is True
        assert "HIGH risk" in decision.reason


class TestT5MediumAutoWithFlag:
    """T5: MEDIUM + flag=on + autonomy L2+ → avtomatik."""

    def test_medium_auto_when_flag_and_autonomy(self) -> None:
        policy = PermissionPolicy(auto_approve_medium=True)
        decision = policy.requires_approval(
            tool_name="order.set_status",
            permission=PermissionLevel.WRITE,
            trust=TrustLevel.SYSTEM,
            risk=RiskLevel.MEDIUM,
            autonomy_level=AutonomyLevel.L3_AGENT,
        )
        assert decision.allowed is True
        assert decision.needs_approval is False


class TestT6MediumFlagOffForcesApproval:
    """T6: MEDIUM + flag=off (default) → tasdiq."""

    def test_medium_default_needs_approval(self) -> None:
        policy = PermissionPolicy()
        decision = policy.requires_approval(
            tool_name="order.set_status",
            permission=PermissionLevel.WRITE,
            trust=TrustLevel.SYSTEM,
            risk=RiskLevel.MEDIUM,
            autonomy_level=AutonomyLevel.L4_AUTONOMOUS,
        )
        assert decision.needs_approval is True
        assert "MEDIUM" in decision.reason


class TestT7LowAutonomyForcesMediumApproval:
    """T7: MEDIUM + flag=on lekin L0/L1 → hali ham tasdiq."""

    def test_medium_requires_approval_at_low_autonomy_even_with_flag(self) -> None:
        policy = PermissionPolicy(auto_approve_medium=True)
        decision = policy.requires_approval(
            tool_name="task.create",
            permission=PermissionLevel.WRITE,
            trust=TrustLevel.SYSTEM,
            risk=RiskLevel.MEDIUM,
            autonomy_level=AutonomyLevel.L1_CONNECTED,
        )
        assert decision.needs_approval is True


class TestT8LowRiskReadAutoAnyAutonomy:
    """T8: READ + LOW — har qanday darajada avtomatik."""

    def test_read_low_auto_at_l0(self) -> None:
        policy = PermissionPolicy()
        decision = policy.requires_approval(
            tool_name="note.list",
            permission=PermissionLevel.READ,
            trust=TrustLevel.SYSTEM,
            risk=RiskLevel.LOW,
            autonomy_level=AutonomyLevel.L0_CHAT,
        )
        assert decision.allowed is True
        assert decision.needs_approval is False


class TestT9UntrustedStillEscalates:
    """T9: UNTRUSTED + WRITE + LOW risk — hali ham tasdiq (trust axis)."""

    def test_untrusted_write_needs_approval_even_low_risk(self) -> None:
        policy = PermissionPolicy(auto_approve_write=True)
        decision = policy.requires_approval(
            tool_name="note.write",
            permission=PermissionLevel.WRITE,
            trust=TrustLevel.UNTRUSTED,
            risk=RiskLevel.LOW,
            autonomy_level=AutonomyLevel.L4_AUTONOMOUS,
        )
        assert decision.needs_approval is True


class TestT10L5DoesNotBypassHigh:
    """T10: L5_MONITORED HIGH ni chetlab o'tolmaydi (V-32)."""

    def test_l5_still_needs_approval_for_high(self) -> None:
        policy = PermissionPolicy(auto_approve_write=True, auto_approve_medium=True)
        decision = policy.requires_approval(
            tool_name="shell.exec",
            permission=PermissionLevel.EXECUTE,
            trust=TrustLevel.SYSTEM,
            risk=RiskLevel.HIGH,
            autonomy_level=AutonomyLevel.L5_MONITORED,
        )
        assert decision.needs_approval is True


class TestT11L5PolicyRow:
    """T11: L5_MONITORED siyosat qatori shakli."""

    def test_l5_policy_shape(self) -> None:
        policy = policy_for(AutonomyLevel.L5_MONITORED)
        assert policy.max_permission == PermissionLevel.EXECUTE
        assert policy.max_goal_iterations == 5
        assert policy.requires_approval_for_execute is True
        assert policy.allows(AutonomyCapability.CONTINUOUS_MONITORING) is True
        # L4 imkoniyatlarini meros oladi
        assert policy.allows(AutonomyCapability.SELF_COMMAND) is True
        assert policy.allows(AutonomyCapability.SELF_IMPROVE) is True


class TestT12L5RankHigherThanL4:
    """T12: L5 rank L4 dan yuqori."""

    def test_l5_rank_is_five(self) -> None:
        assert AutonomyLevel.L5_MONITORED.rank == 5
        assert AutonomyLevel.L5_MONITORED.rank > AutonomyLevel.L4_AUTONOMOUS.rank

    def test_l5_opens_continuous_monitoring(self) -> None:
        assert allows(AutonomyLevel.L5_MONITORED, AutonomyCapability.CONTINUOUS_MONITORING)
        # L4 uni bermaydi
        assert not allows(AutonomyLevel.L4_AUTONOMOUS, AutonomyCapability.CONTINUOUS_MONITORING)


class TestT13ToolOverrideBeatsTable:
    """T13: subclass override jadvaldan yuqori (aynan mos nom)."""

    def test_subclass_override_wins(self) -> None:
        # `note.write` jadvalda MEDIUM. Subclass HIGH deb belgilaydi.
        overridden = _StubTool(name="note.write", risk=RiskLevel.HIGH)
        assert overridden.risk_level is RiskLevel.HIGH

        policy = PermissionPolicy(auto_approve_write=True, auto_approve_medium=True)
        decision = policy.requires_approval(
            tool=overridden,
            permission=PermissionLevel.WRITE,
            trust=TrustLevel.SYSTEM,
            autonomy_level=AutonomyLevel.L4_AUTONOMOUS,
        )
        assert decision.needs_approval is True
        assert "HIGH" in decision.reason


class TestT14UnknownToolDefaultsLow:
    """T14: noma'lum tool nomi — LOW, KeyError yo'q."""

    def test_unknown_name_defaults_to_low_and_allows(self) -> None:
        policy = PermissionPolicy()
        # Umuman jadvalda yo'q, tool obyekti ham berilmagan
        decision = policy.requires_approval(
            tool_name="never.registered",
            permission=PermissionLevel.READ,
            trust=TrustLevel.SYSTEM,
            autonomy_level=AutonomyLevel.L3_AGENT,
        )
        assert decision.allowed is True
        assert decision.needs_approval is False


class TestT15ApprovalRequestCarriesRisk:
    """T15: ApprovalRequest risk_level maydonini saqlaydi."""

    def test_approval_request_stores_risk_level(self) -> None:
        service = ApprovalService()
        req = service.request_approval(
            run_id=uuid.uuid4(),
            reason="test — HIGH risk tool tasdiq",
            requested_permission=PermissionLevel.EXECUTE,
            tool_name="shell.exec",
            risk_level=RiskLevel.HIGH,
        )
        assert req.risk_level is RiskLevel.HIGH

    def test_approval_request_risk_level_optional(self) -> None:
        """Risk axis'ni bilmagan eski chaqiruvchi — None qoladi."""
        service = ApprovalService()
        req = service.request_approval(
            run_id=uuid.uuid4(),
            reason="test",
            requested_permission=PermissionLevel.WRITE,
        )
        assert req.risk_level is None


class TestRiskResolutionOrder:
    """Explicit risk arg > tool.risk_level > table > LOW."""

    def test_explicit_risk_arg_wins(self) -> None:
        policy = PermissionPolicy(auto_approve_write=True, auto_approve_medium=True)
        # tool_name jadvalda LOW (agent.list), lekin biz HIGH beramiz
        decision = policy.requires_approval(
            tool_name="agent.list",
            permission=PermissionLevel.READ,
            trust=TrustLevel.SYSTEM,
            risk=RiskLevel.HIGH,
            autonomy_level=AutonomyLevel.L4_AUTONOMOUS,
        )
        assert decision.needs_approval is True

    def test_tool_object_over_name(self) -> None:
        """tool berilsa risk_level tool'dan olinadi."""
        overridden = _StubTool(name="agent.list", risk=RiskLevel.HIGH)
        policy = PermissionPolicy()
        decision = policy.requires_approval(
            tool=overridden,
            permission=PermissionLevel.READ,
            trust=TrustLevel.SYSTEM,
            autonomy_level=AutonomyLevel.L4_AUTONOMOUS,
        )
        assert decision.needs_approval is True


class TestBackCompatCheck:
    """Eski `check()` metod hali ham ishlaydi — refactor buzmaydi."""

    def test_check_still_works_for_read(self) -> None:
        policy = PermissionPolicy()
        d = policy.check(PermissionLevel.READ, TrustLevel.OWNER, tool_name="time.now")
        assert d.allowed is True

    def test_check_high_risk_tools_still_denied(self) -> None:
        policy = PermissionPolicy()
        d = policy.check(PermissionLevel.WRITE, TrustLevel.SYSTEM, tool_name="shell.exec")
        assert d.needs_approval is True
