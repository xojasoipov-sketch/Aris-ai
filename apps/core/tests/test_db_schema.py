"""Z1.4 — DB sxemasi va cheklovlari testlari."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from zet.db.base import utcnow
from zet.db.models import (
    Approval,
    AuditLog,
    Conversation,
    CostLedger,
    KillSwitch,
    Message,
    Owner,
    Plan,
    QuotaLedger,
    Run,
    Step,
    ToolCall,
)
from zet.db.session import AuditLogImmutableError
from zet.domain.enums import (
    ApprovalStatus,
    MessageRole,
    ModelTier,
    PermissionLevel,
    RunStatus,
    RunTrigger,
    StepStatus,
    TaskClass,
    TrustLevel,
)


async def _make_run(session: AsyncSession, owner: Owner, **kw: object) -> Run:
    run = Run(
        owner_id=owner.id,
        command_text=kw.pop("command_text", "test buyruq"),  # type: ignore[arg-type]
        trace_id=uuid.uuid4().hex,
        **kw,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


class TestOwnerAndConversation:
    async def test_owner_defaults_to_admin(self, owner: Owner) -> None:
        assert owner.permission_level is PermissionLevel.ADMIN
        assert owner.is_active is True

    async def test_external_id_is_unique(self, session: AsyncSession, owner: Owner) -> None:
        session.add(Owner(external_id=owner.external_id))
        with pytest.raises(IntegrityError):
            await session.commit()

    async def test_timestamps_are_timezone_aware(self, owner: Owner) -> None:
        assert owner.created_at.tzinfo is not None
        assert owner.updated_at.tzinfo is not None

    async def test_message_defaults_to_owner_trust(
        self, session: AsyncSession, conversation: Conversation
    ) -> None:
        msg = Message(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content="Salom",
        )
        session.add(msg)
        await session.commit()
        await session.refresh(msg)
        assert msg.trust_level is TrustLevel.OWNER
        assert msg.meta == {}

    async def test_untrusted_message_can_be_stored(
        self, session: AsyncSession, conversation: Conversation
    ) -> None:
        """A-05: forward qilingan tashqi matn UNTRUSTED bo'ladi."""
        msg = Message(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content="<web sahifadan olingan matn>",
            trust_level=TrustLevel.UNTRUSTED,
        )
        session.add(msg)
        await session.commit()
        assert msg.trust_level is TrustLevel.UNTRUSTED


class TestRun:
    async def test_defaults(self, session: AsyncSession, owner: Owner) -> None:
        run = await _make_run(session, owner)
        assert run.status is RunStatus.PENDING
        assert run.trigger is RunTrigger.MANUAL
        assert run.depth == 0
        assert run.spent_usd == 0.0
        assert run.verified_ok is None

    async def test_is_autonomous_property(self, session: AsyncSession, owner: Owner) -> None:
        manual = await _make_run(session, owner)
        scheduled = await _make_run(session, owner, trigger=RunTrigger.SCHEDULE)
        assert manual.is_autonomous is False
        assert scheduled.is_autonomous is True

    async def test_negative_depth_rejected(self, session: AsyncSession, owner: Owner) -> None:
        """A-07: depth cheklovi DB darajasida ham himoyalangan."""
        session.add(Run(owner_id=owner.id, command_text="x", trace_id="t", depth=-1))
        with pytest.raises(IntegrityError):
            await session.commit()

    async def test_negative_spend_rejected(self, session: AsyncSession, owner: Owner) -> None:
        session.add(Run(owner_id=owner.id, command_text="x", trace_id="t", spent_usd=-0.5))
        with pytest.raises(IntegrityError):
            await session.commit()

    async def test_parent_child_chain(self, session: AsyncSession, owner: Owner) -> None:
        """Agent trigger'i orqali tug'ilgan run zanjiri."""
        parent = await _make_run(session, owner)
        child = await _make_run(
            session, owner, parent_run_id=parent.id, depth=1, trigger=RunTrigger.AGENT
        )
        assert child.parent_run_id == parent.id
        assert child.depth == 1


class TestPlanAndStep:
    async def test_one_plan_per_run(self, session: AsyncSession, owner: Owner) -> None:
        run = await _make_run(session, owner)
        session.add(Plan(run_id=run.id, summary="birinchi"))
        await session.commit()
        session.add(Plan(run_id=run.id, summary="ikkinchi"))
        with pytest.raises(IntegrityError):
            await session.commit()

    async def test_step_position_unique_per_plan(self, session: AsyncSession, owner: Owner) -> None:
        run = await _make_run(session, owner)
        plan = Plan(run_id=run.id, summary="reja")
        session.add(plan)
        await session.commit()

        session.add(Step(plan_id=plan.id, position=0, description="a"))
        await session.commit()
        session.add(Step(plan_id=plan.id, position=0, description="b"))
        with pytest.raises(IntegrityError):
            await session.commit()

    async def test_step_defaults(self, session: AsyncSession, owner: Owner) -> None:
        run = await _make_run(session, owner)
        plan = Plan(run_id=run.id, summary="reja")
        session.add(plan)
        await session.commit()

        step = Step(plan_id=plan.id, position=0, description="eslatma yoz")
        session.add(step)
        await session.commit()
        await session.refresh(step)

        assert step.status is StepStatus.PENDING
        assert step.permission_required is PermissionLevel.READ
        assert step.trust_context is TrustLevel.OWNER
        assert step.depends_on == []
        assert step.attempt == 0

    async def test_steps_ordered_by_position(self, session: AsyncSession, owner: Owner) -> None:
        run = await _make_run(session, owner)
        plan = Plan(run_id=run.id, summary="reja")
        session.add(plan)
        await session.commit()

        for pos in (2, 0, 1):
            session.add(Step(plan_id=plan.id, position=pos, description=f"qadam {pos}"))
        await session.commit()

        loaded = (
            (
                await session.execute(
                    select(Step).where(Step.plan_id == plan.id).order_by(Step.position)
                )
            )
            .scalars()
            .all()
        )
        assert [s.position for s in loaded] == [0, 1, 2]

    async def test_cascade_delete_run_removes_plan_and_steps(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        run = await _make_run(session, owner)
        plan = Plan(run_id=run.id, summary="reja")
        session.add(plan)
        await session.commit()
        session.add(Step(plan_id=plan.id, position=0, description="a"))
        await session.commit()

        await session.delete(run)
        await session.commit()

        assert (await session.execute(select(Plan))).scalars().first() is None
        assert (await session.execute(select(Step))).scalars().first() is None


class TestToolCall:
    async def test_records_trust_and_permission(self, session: AsyncSession, owner: Owner) -> None:
        run = await _make_run(session, owner)
        call = ToolCall(
            run_id=run.id,
            tool_name="web.fetch",
            permission_level=PermissionLevel.READ,
            output_trust_level=TrustLevel.UNTRUSTED,
            input={"url": "https://example.com"},
            output={"text": "..."},
            ok=True,
            latency_ms=120,
        )
        session.add(call)
        await session.commit()
        await session.refresh(call)

        assert call.output_trust_level is TrustLevel.UNTRUSTED
        assert call.dry_run is False

    async def test_defaults(self, session: AsyncSession, owner: Owner) -> None:
        run = await _make_run(session, owner)
        call = ToolCall(run_id=run.id, tool_name="time.now", permission_level=PermissionLevel.READ)
        session.add(call)
        await session.commit()
        await session.refresh(call)

        assert call.ok is False
        assert call.output_trust_level is TrustLevel.SYSTEM
        assert call.input == {}


class TestApproval:
    async def test_expiry_check(self, session: AsyncSession, owner: Owner) -> None:
        run = await _make_run(session, owner)
        past = datetime.now(UTC) - timedelta(minutes=1)
        approval = Approval(
            run_id=run.id,
            reason="shell.exec chaqirilmoqda",
            requested_permission=PermissionLevel.EXECUTE,
            expires_at=past,
        )
        session.add(approval)
        await session.commit()

        assert approval.status is ApprovalStatus.PENDING
        assert approval.is_expired() is True

    async def test_not_expired_when_future(self, session: AsyncSession, owner: Owner) -> None:
        run = await _make_run(session, owner)
        approval = Approval(
            run_id=run.id,
            reason="fayl o'chirish",
            requested_permission=PermissionLevel.ADMIN,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        session.add(approval)
        await session.commit()
        assert approval.is_expired() is False


class TestAuditLogIsAppendOnly:
    """V-33: audit jurnali o'zgartirilmaydi va o'chirilmaydi."""

    async def test_insert_works(self, session: AsyncSession) -> None:
        entry = AuditLog(actor="owner", action="approval.granted", target="run:123")
        session.add(entry)
        await session.commit()
        assert entry.ts.tzinfo is not None

    async def test_update_is_blocked(self, session: AsyncSession) -> None:
        entry = AuditLog(actor="owner", action="approval.granted")
        session.add(entry)
        await session.commit()

        entry.action = "approval.denied"
        with pytest.raises(AuditLogImmutableError):
            await session.commit()

    async def test_delete_is_blocked(self, session: AsyncSession) -> None:
        entry = AuditLog(actor="owner", action="killswitch.engaged")
        session.add(entry)
        await session.commit()

        await session.delete(entry)
        with pytest.raises(AuditLogImmutableError):
            await session.commit()

    async def test_has_no_updated_at(self) -> None:
        """`updated_at` ustuni bo'lishi mantiqan xato bo'lardi."""
        assert "updated_at" not in AuditLog.__table__.columns


class TestKillSwitch:
    async def test_singleton_constraint(self, session: AsyncSession) -> None:
        session.add(KillSwitch(singleton=True))
        await session.commit()
        session.add(KillSwitch(singleton=True))
        with pytest.raises(IntegrityError):
            await session.commit()

    async def test_defaults_to_disengaged(self, session: AsyncSession) -> None:
        ks = KillSwitch()
        session.add(ks)
        await session.commit()
        await session.refresh(ks)
        assert ks.engaged is False


class TestCostAndQuotaLedger:
    async def test_cost_entry(self, session: AsyncSession, owner: Owner) -> None:
        run = await _make_run(session, owner)
        entry = CostLedger(
            run_id=run.id,
            provider="anthropic",
            model="claude-haiku-4-5",
            tier=ModelTier.T2_CHEAP,
            task_class=TaskClass.NORMAL,
            input_tokens=25_000,
            output_tokens=3_600,
            usd=0.043,
            latency_ms=1500,
            verified_ok=True,
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        assert entry.is_autonomous is False

    async def test_negative_cost_rejected(self, session: AsyncSession) -> None:
        session.add(
            CostLedger(
                provider="p",
                model="m",
                tier=ModelTier.T0_LOCAL,
                task_class=TaskClass.SIMPLE,
                usd=-1.0,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()

    async def test_quota_remaining_and_exhausted(self, session: AsyncSession) -> None:
        now = utcnow()
        q = QuotaLedger(
            provider="google",
            window="day",
            window_start=now,
            used=1400,
            limit_value=1500,
            resets_at=now + timedelta(days=1),
        )
        session.add(q)
        await session.commit()

        assert q.remaining == 100
        assert q.is_exhausted is False

        q.used = 1500
        await session.commit()
        assert q.remaining == 0
        assert q.is_exhausted is True

    async def test_quota_window_unique(self, session: AsyncSession) -> None:
        now = utcnow()
        for _ in range(2):
            session.add(
                QuotaLedger(
                    provider="groq",
                    window="minute",
                    window_start=now,
                    limit_value=30,
                    resets_at=now + timedelta(minutes=1),
                )
            )
        with pytest.raises(IntegrityError):
            await session.commit()
