"""HIGH #2 audit fix (KONSOLIDATSIYA v2) — per-step checkpoint testlari.

Foydalanuvchi talabi (ustuvorlik #1, "eng xavfli"): approval-resume
paytida rejaning BOSHIDAN qayta bajarilishi — idempotent bo'lmagan
WRITE/EXECUTE qadam (masalan xabar yuborish) IKKINCHI marta bajarilib
qolishi. Bu testlar aynan shu ssenariyni qulflaydi:

    3 qadamli reja: 0-qadam (READ, avtomatik) -> 1-qadam (WRITE, "xabar
    yuborish", avtomatik) -> 2-qadam (EXECUTE, HAR DOIM tasdiq talab
    qiladi -> "uzilish"). Tasdiqdan keyin `resume()` chaqirilganda —
    0- va 1-qadamlar QAYTA BAJARILMASLIGI kerak (checkpoint'dan
    tiklanishi kerak), faqat 2-qadam bajariladi.

REAL Executor/PermissionPolicy/RunStore/ApprovalService/Orchestrator —
soxta emas. "Restart simulyatsiyasi" — A1 audit bilan bir xil uslub:
ikkinchi bosqichda BUTUNLAY YANGI RunStore/ApprovalService/Orchestrator
quriladi va faqat DB'dan (`load_pending_runs`/`load_pending_approvals`)
tiklanadi — hech qanday xotira ulashilmaydi.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.core.orchestrator import Orchestrator, RunStore
from zet.core.run_checkpoint import load_pending_approvals, load_pending_runs
from zet.db.bootstrap import get_or_create_owner
from zet.domain.command import Command
from zet.domain.enums import ApprovalStatus, PermissionLevel, RunStatus, TrustLevel
from zet.domain.plan import Plan, PlanStep
from zet.security.approvals import ApprovalService
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.tools.base import Tool
from zet.tools.registry import ToolRegistry


class _TrackingReadTool(Tool):
    """READ tool — chaqiruvlarni yozib boradi (checkpoint skip'ini isbotlash uchun)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "step0.read"

    @property
    def description(self) -> str:
        return "test uchun — READ, chaqiruvlarni yozadi"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    async def _execute(self, params: dict[str, Any]) -> Any:
        self.calls.append(dict(params))
        return {"ok": True}


class _TrackingSendTool(Tool):
    """WRITE tool — "xabar yuborish" simulyatsiyasi, chaqiruvlarni yozib boradi.

    MUHIM: bu — aynan idempotent BO'LMAGAN yon effektli amal namunasi
    (foydalanuvchi so'ragan "masalan xabar yuborish"). Ikki marta
    chaqirilsa — ikki marta xabar yuboriladi degani."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "message.send"

    @property
    def description(self) -> str:
        return "test uchun — WRITE, xabar yuborish simulyatsiyasi"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"text": {"type": "string"}}}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.WRITE

    async def _execute(self, params: dict[str, Any]) -> Any:
        self.calls.append(dict(params))
        return {"sent": True}


def _three_step_plan() -> Plan:
    return Plan(
        summary="Uch qadamli: o'qish -> xabar yuborish -> xavfli amal",
        steps=[
            PlanStep(
                position=0,
                description="Ma'lumot o'qish",
                tool_name="step0.read",
                permission_required=PermissionLevel.READ,
                depends_on=[],
            ),
            PlanStep(
                position=1,
                description="Egaga xabar yuborish",
                tool_name="message.send",
                tool_params={"text": "salom"},
                permission_required=PermissionLevel.WRITE,
                depends_on=[0],
            ),
            PlanStep(
                position=2,
                description="Xavfli amal (har doim tasdiq talab qiladi)",
                tool_name=None,
                permission_required=PermissionLevel.EXECUTE,
                depends_on=[1],
            ),
        ],
    )


class TestApprovalResumeIsIdempotent:
    """HIGH #2 (KONSOLIDATSIYA v2) — asosiy talab: WRITE qadam
    (xabar yuborish) resume()'dan keyin FAQAT BIR MARTA bajariladi."""

    async def test_write_step_not_repeated_after_restart_and_resume(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        session: AsyncSession,
    ) -> None:
        owner_ext = "e2e-step-checkpoint"
        await get_or_create_owner(session, external_id=owner_ext)
        await session.commit()

        registry = ToolRegistry()
        read_tool = _TrackingReadTool()
        send_tool = _TrackingSendTool()
        registry.register(read_tool)
        registry.register(send_tool)

        policy = PermissionPolicy()  # default: WRITE avtomatik, EXECUTE — har doim tasdiq
        killswitch = KillSwitchState()
        plan = _three_step_plan()

        # ── 1-BOSQICH: run boshlaymiz, 2-qadamda "uzilamiz" ──────────
        store1 = RunStore(session_factory=session_factory, owner_external_id=owner_ext)
        approvals1 = ApprovalService(session_factory=session_factory)
        orch1 = Orchestrator(
            router=None,  # type: ignore[arg-type]
            tool_registry=registry,
            permission_policy=policy,
            approval_service=approvals1,
            killswitch=killswitch,
            run_store=store1,
            budget_usd=1.0,
        )
        record = store1.create(
            Command(text="uch qadamli buyruq", channel="cli", trust_level=TrustLevel.OWNER)
        )
        record.plan = plan
        record.steps_total = 3

        result1 = await orch1._run_plan(record, trust=TrustLevel.OWNER, dry_run=False)

        assert result1.status == RunStatus.AWAITING_APPROVAL
        # 0- va 1-qadam AYNAN BIR MARTA bajarilgan
        assert len(read_tool.calls) == 1
        assert send_tool.calls == [{"text": "salom"}], (
            "1-bosqichda xabar yuborish qadami bir marta bajarilishi kerak edi"
        )

        run_id = result1.run_id

        # ── "RESTART": BUTUNLAY YANGI store/approvals/orchestrator ──
        # Hech qanday xotira ulashilmaydi — faqat DB orqali tiklanadi
        # (A1 audit bilan bir xil uslub).
        store2 = RunStore(session_factory=session_factory, owner_external_id=owner_ext)
        approvals2 = ApprovalService(session_factory=session_factory)
        restored_runs = await load_pending_runs(session_factory, store2)
        restored_approvals = await load_pending_approvals(session_factory, approvals2)
        assert restored_runs == 1
        assert restored_approvals == 1

        record2 = store2.get(run_id)
        # Reja HAM DB'dan tiklangan bo'lishi kerak — aks holda resume()
        # "Reja mavjud emas" bilan yiqiladi (HIGH #2 topilmasi).
        assert record2.plan is not None
        assert len(record2.plan.steps) == 3

        pending = approvals2.pending_for_run(run_id)
        assert len(pending) == 1
        approval = pending[0]
        assert approval.status == ApprovalStatus.PENDING
        assert approval.step_position == 2

        orch2 = Orchestrator(
            router=None,  # type: ignore[arg-type]
            tool_registry=registry,  # BIR XIL registry — chaqiruv sonini kuzatish uchun
            permission_policy=policy,
            approval_service=approvals2,
            killswitch=killswitch,
            run_store=store2,
            budget_usd=1.0,
        )

        # ── 2-BOSQICH: tasdiqlaymiz va resume() qilamiz ──────────────
        record2 = orch2.approve(approval.id)
        result2 = await orch2.resume(run_id)

        assert result2.status == RunStatus.DONE, result2.error

        # ══ ENG MUHIM DALIL (HIGH #2) ══════════════════════════════
        # 0- va 1-qadam HALI HAM faqat bir marta bajarilgan — resume()
        # ularni QAYTA bajarmadi. Agar checkpoint ishlamasa, bu sonlar
        # 2 bo'lar edi (xabar IKKI MARTA yuborilgan bo'lardi).
        assert len(read_tool.calls) == 1, (
            f"HIGH #2 BUZILDI: 0-qadam qayta bajarildi ({len(read_tool.calls)} marta)"
        )
        assert send_tool.calls == [{"text": "salom"}], (
            f"HIGH #2 BUZILDI: xabar yuborish qadami qayta bajarildi "
            f"({len(send_tool.calls)} marta) — bu real dunyoda xabarni IKKI "
            f"MARTA yuborish degani"
        )
        # 2-qadam esa AYNAN bir marta (tasdiqdan keyin) bajarilgan bo'lishi kerak
        assert result2.steps_done == 3


class TestExecutorSkipsCheckpointedSteps:
    """Birlik darajasidagi test — `Executor.execute_plan(completed_steps=...)`
    berilgan pozitsiyalarni HECH QACHON qayta bajarmasligini to'g'ridan-
    to'g'ri tekshiradi (Orchestrator/DB qatlamisiz)."""

    async def test_completed_step_tool_never_called_again(self) -> None:
        from zet.core.executor import Executor, StepResult
        from zet.domain.enums import StepStatus
        from zet.domain.tool import ToolResult

        registry = ToolRegistry()
        send_tool = _TrackingSendTool()
        registry.register(send_tool)

        step = PlanStep(
            position=0,
            description="Xabar yuborish",
            tool_name="message.send",
            tool_params={"text": "salom"},
            permission_required=PermissionLevel.WRITE,
        )
        plan = Plan(summary="Bitta qadam", steps=[step])

        executor = Executor(
            registry=registry,
            policy=PermissionPolicy(),
            killswitch=KillSwitchState(),
            budget_usd=1.0,
            router=None,
        )

        # Checkpoint — qadam ALLAQACHON DONE deb "eslatiladi", lekin
        # tool HECH QACHON chaqirilmagan (soxta oldindan tayyorlangan
        # natija — aynan DB'dan tiklangan holatni simulyatsiya qiladi).
        fake_prior_result = StepResult(
            step,
            status=StepStatus.DONE,
            tool_result=ToolResult(tool_name="message.send", success=True, output={"sent": True}),
        )

        ctx = await executor.execute_plan(
            plan,
            trust=TrustLevel.OWNER,
            completed_steps={0: fake_prior_result},
        )

        assert send_tool.calls == [], (
            "Checkpoint qilingan qadam uchun tool UMUMAN chaqirilmasligi kerak"
        )
        assert ctx.results[0].status == StepStatus.DONE
