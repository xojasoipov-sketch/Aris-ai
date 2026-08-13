"""Z.PART6 — RecoveryEngine (FAIL→DIAGNOSE→FIX→RETRY→VERIFY) testlari.

Master Spec PART 6 va AUTONOMY_AUDIT §2.5: verify_run FAIL bo'lganda
arzon T1_FREE LLM'dan diagnos so'ralib tuzatish qadamlari qo'shiladi.
Qattiq MAX_RETRIES=2 chegara — uncontrolled loop yo'q. Exhaust bo'lsa —
halol recovered=False qaytadi (soxta muvaffaqiyat emas).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from zet.core.executor import ExecutionContext, Executor, StepResult
from zet.core.orchestrator import Orchestrator, RunStore
from zet.core.recovery import (
    DIAGNOSIS_MAX_FIX_STEPS,
    DIAGNOSIS_MAX_OUTPUT_CHARS,
    MAX_RETRIES,
    Diagnosis,
    RecoveryApprovalRequiredError,
    RecoveryEngine,
    RecoveryOutcome,
)
from zet.domain.command import Command
from zet.domain.enums import (
    ApprovalStatus,
    PermissionLevel,
    RunStatus,
    StepStatus,
    TrustLevel,
)
from zet.domain.plan import Plan, PlanStep
from zet.domain.tool import ToolResult, Verification
from zet.llm.base import LLMError
from zet.security.approvals import ApprovalService
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.tools.base import Tool
from zet.tools.registry import ToolRegistry

# ── Fake yordamchilar ──────────────────────────────────────────────


class _FakeLLMResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeLLM:
    """Deterministik LLMProvider — .complete() ketma-ket javob qaytaradi.

    Har chaqiruv `responses` navbatidan bittasini oladi. `LLMError`
    bo'lgan javoblar chaqiruvda istisno ko'taradi (T7 uchun)."""

    def __init__(self, responses: list[str | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def complete(  # type: ignore[no-untyped-def]
        self, *, messages, system=None, max_tokens=None, **_
    ):
        self.calls.append({"messages": list(messages), "system": system, "max_tokens": max_tokens})
        if not self._responses:
            raise LLMError("javoblar tugadi")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeLLMResponse(item)


class _FakeExecutor:
    """Executor stubi — execute_plan chaqirilganda oldindan sozlangan
    ExecutionContext qaytaradi. Har chaqiruvda `on_execute` chaqiruvchisiga
    yangi ctx tayyorlash imkonini beradi (attempt bosqichi bo'yicha)."""

    def __init__(self, contexts: list[ExecutionContext]) -> None:
        self._contexts = list(contexts)
        self.calls: list[dict[str, Any]] = []
        self.spent_usd = 0.0

    async def execute_plan(  # type: ignore[no-untyped-def]
        self,
        plan,
        *,
        approved_steps=None,
        trust=TrustLevel.OWNER,
        dry_run=False,
        completed_steps=None,
        step_done_fn=None,
    ):
        self.calls.append(
            {
                "plan": plan,
                "approved_steps": set(approved_steps or set()),
                "trust": trust,
                "dry_run": dry_run,
                "completed_steps": dict(completed_steps or {}),
            }
        )
        if not self._contexts:
            raise AssertionError("FakeExecutor: navbatga qo'yilgan ctx tugadi")
        return self._contexts.pop(0)


class _StubVerifier:
    """Verifier stubi — verify_step ketma-ket sozlangan `Verification` qaytaradi."""

    def __init__(self, verdicts: list[Verification]) -> None:
        self._verdicts = list(verdicts)
        self.calls: list[tuple[PlanStep, ToolResult | None]] = []

    async def verify_step(self, step: PlanStep, tool_result: ToolResult | None) -> Verification:
        self.calls.append((step, tool_result))
        if not self._verdicts:
            # Test yozuvchisi navbatni tugatib qo'ymasin — default fail
            return Verification(ok=False, reason="stub tugadi")
        return self._verdicts.pop(0)


# ── Fikstura yordamchilari ─────────────────────────────────────────


def _read_step(position: int = 0, description: str = "O'qish") -> PlanStep:
    return PlanStep(
        position=position,
        description=description,
        tool_name="test.read",
        permission_required=PermissionLevel.READ,
        expected_outcome="natija bo'lishi",
    )


def _plan(*steps: PlanStep, summary: str = "Test reja") -> Plan:
    return Plan(summary=summary, steps=list(steps))


def _tool_result(
    success: bool = True,
    output: object = "natija",
    error: str | None = None,
) -> ToolResult:
    return ToolResult(
        tool_name="test.read",
        success=success,
        output=output,
        error=error,
    )


def _ctx_with(plan: Plan, results: dict[int, StepResult]) -> ExecutionContext:
    ctx = ExecutionContext(plan)
    for pos, res in results.items():
        ctx.record(pos, res)
    return ctx


def _fix_json(
    root_cause: str = "web muvaffaqiyatsiz",
    tool_name: str | None = "test.read",
    description: str = "Boshqa parametr bilan qayta urinish",
    n_steps: int = 1,
    confidence: float = 0.8,
    expected_outcome: str = "yangi natija",
    permission_required: str = "read",
) -> str:
    steps = []
    for i in range(n_steps):
        steps.append(
            {
                "description": f"{description} #{i}",
                "tool_name": tool_name,
                "tool_params": {},
                "expected_outcome": expected_outcome,
                "permission_required": permission_required,
            }
        )
    return json.dumps(
        {
            "root_cause": root_cause,
            "confidence": confidence,
            "fix_steps": steps,
        }
    )


def _make_engine(
    llm: _FakeLLM,
    executor_contexts: list[ExecutionContext] | None = None,
    verify_results: list[Verification] | None = None,
    max_retries: int = MAX_RETRIES,
    tool_names: set[str] | None = None,
) -> tuple[RecoveryEngine, list[_FakeExecutor], _StubVerifier]:
    executors: list[_FakeExecutor] = []
    contexts = list(executor_contexts or [])

    def factory() -> _FakeExecutor:
        # Har urinishga bitta ctx — factory har chaqiruvda birinchisini uzatadi.
        exe = _FakeExecutor(contexts=[contexts.pop(0)] if contexts else [])
        executors.append(exe)
        return exe

    verifier = _StubVerifier(verify_results or [])
    engine = RecoveryEngine(
        llm_provider=llm,  # type: ignore[arg-type]
        executor_factory=factory,  # type: ignore[arg-type]
        verifier=verifier,  # type: ignore[arg-type]
        max_retries=max_retries,
        tool_names=tool_names or {"test.read", "test.write"},
    )
    return engine, executors, verifier


# ── Testlar ────────────────────────────────────────────────────────


class TestAttemptShortCircuit:
    """T1 — bo'sh failed_verifications → recovered=True, LLM chaqirilmaydi."""

    async def test_no_failures_returns_recovered(self) -> None:
        llm = _FakeLLM(responses=[])
        engine, _executors, _verifier_stub = _make_engine(llm)

        step = _read_step()
        plan = _plan(step)
        ctx = _ctx_with(plan, {})

        outcome = await engine.attempt(
            plan=plan,
            ctx=ctx,
            failed_verifications=[],
            trust=TrustLevel.OWNER,
        )

        assert outcome.recovered is True
        assert outcome.attempts == 0
        assert outcome.diagnoses == []
        assert llm.calls == [], "LLM chaqirilmasligi kerak edi"
        assert _executors == [], "Executor ham chaqirilmasligi kerak edi"


class TestSingleFixSucceeds:
    """T2 — bir diagnos→fix→retry sikli muvaffaqiyatli."""

    async def test_first_attempt_recovers(self) -> None:
        step = _read_step(position=0)
        plan = _plan(step)
        # Asl ctx — qadam yiqilgan
        original_result = StepResult(
            step,
            status=StepStatus.FAILED,
            tool_result=_tool_result(success=False, error="404 not found"),
        )
        ctx = _ctx_with(plan, {0: original_result})
        # Retry ctx — recovery qadamdan keyin, asl qadam yangi
        # muvaffaqiyatli tool_result bilan (recovery step state'ni tuzatdi)
        new_ok_result = StepResult(
            step,
            status=StepStatus.DONE,
            tool_result=_tool_result(success=True, output="tuzatilgan natija"),
        )
        retry_ctx = _ctx_with(plan, {0: new_ok_result})

        llm = _FakeLLM(responses=[_fix_json()])
        engine, _executors, _verifier_stub = _make_engine(
            llm,
            executor_contexts=[retry_ctx],
            verify_results=[Verification(ok=True, reason="tuzatildi", auto=True)],
        )

        outcome = await engine.attempt(
            plan=plan,
            ctx=ctx,
            failed_verifications=[(step, Verification(ok=False, reason="tool xato"))],
            trust=TrustLevel.OWNER,
        )

        assert outcome.recovered is True
        assert outcome.attempts == 1
        assert len(outcome.diagnoses) == 1
        # Kengaytirilgan reja — asl + 1 qadam
        assert len(outcome.extended_plan.steps) == len(plan.steps) + 1
        # Yangi qadam depends_on ga yiqilgan qadamning pozitsiyasi kirdi
        new_step = outcome.extended_plan.steps[-1]
        assert new_step.depends_on == [step.position]
        assert new_step.position == step.position + 1
        assert len(_executors) == 1
        assert len(_verifier_stub.calls) == 1


class TestMaxRetriesEnforced:
    """T3 — har urinish FAIL bo'lsa MAX_RETRIES=2 dan oshmaydi."""

    async def test_max_retries_is_two_by_default(self) -> None:
        assert MAX_RETRIES == 2

        step = _read_step()
        plan = _plan(step)
        failed_result = StepResult(
            step,
            status=StepStatus.FAILED,
            tool_result=_tool_result(success=False, error="boom"),
        )
        ctx = _ctx_with(plan, {0: failed_result})

        # Har urinishga o'z retry ctx'i (bir xil yiqilgan qadam)
        retry_ctx_1 = _ctx_with(plan, {0: failed_result})
        retry_ctx_2 = _ctx_with(plan, {0: failed_result})

        llm = _FakeLLM(responses=[_fix_json(), _fix_json()])
        engine, _executors, _verifier_stub = _make_engine(
            llm,
            executor_contexts=[retry_ctx_1, retry_ctx_2],
            verify_results=[
                Verification(ok=False, reason="hali ham xato"),
                Verification(ok=False, reason="hali ham xato"),
            ],
        )

        outcome = await engine.attempt(
            plan=plan,
            ctx=ctx,
            failed_verifications=[(step, Verification(ok=False, reason="tool xato"))],
            trust=TrustLevel.OWNER,
        )

        assert outcome.recovered is False
        assert outcome.attempts == 2
        assert len(llm.calls) == 2, "LLM aynan 2 marta chaqirilishi kerak edi"
        assert len(outcome.diagnoses) == 2
        assert outcome.final_verification.ok is False


class TestParseErrorConsumesAttempt:
    """T4 — buzilgan LLM javobi bir urinishni yeydi (cheksiz loop yo'q)."""

    async def test_bad_json_then_good_recovers_second(self) -> None:
        step = _read_step()
        plan = _plan(step)
        failed_result = StepResult(
            step,
            status=StepStatus.FAILED,
            tool_result=_tool_result(success=False, error="xato"),
        )
        ctx = _ctx_with(plan, {0: failed_result})

        ok_result = StepResult(
            step,
            status=StepStatus.DONE,
            tool_result=_tool_result(success=True, output="tuzatildi"),
        )
        retry_ctx_2 = _ctx_with(plan, {0: ok_result})

        # 1-chaqiruv: JSON emas; 2-chaqiruv: to'g'ri
        llm = _FakeLLM(responses=["not json", _fix_json()])
        engine, _executors, _verifier_stub = _make_engine(
            llm,
            executor_contexts=[retry_ctx_2],
            verify_results=[Verification(ok=True, reason="tuzatildi")],
        )

        outcome = await engine.attempt(
            plan=plan,
            ctx=ctx,
            failed_verifications=[(step, Verification(ok=False, reason="tool xato"))],
            trust=TrustLevel.OWNER,
        )

        assert outcome.recovered is True
        assert outcome.attempts == 2
        assert len(llm.calls) == 2
        assert len(outcome.diagnoses) == 2
        # Birinchi diagnos — bo'sh fix_steps, sabab parse failure
        assert outcome.diagnoses[0].fix_steps == []
        assert "parse" in outcome.diagnoses[0].root_cause.lower()


class TestDagValidityPreserved:
    """T5 — kengaytirilgan reja DAG bo'lib qoladi (PlanValidationError yo'q)."""

    async def test_extended_plan_dag_ok(self) -> None:
        # Reja: [0] → [1] → [2], depends_on [1]->0, [2]->1
        s0 = PlanStep(
            position=0,
            description="A",
            tool_name="test.read",
            permission_required=PermissionLevel.READ,
        )
        s1 = _read_step(position=1, description="B")
        s2 = PlanStep(
            position=2,
            description="C",
            tool_name="test.read",
            permission_required=PermissionLevel.READ,
            depends_on=[1],
        )
        plan = _plan(s0, s1.model_copy(update={"depends_on": [0]}), s2)
        failed_step = plan.steps[1]  # position=1

        failed_result = StepResult(
            failed_step,
            status=StepStatus.FAILED,
            tool_result=_tool_result(success=False, error="xato"),
        )
        ctx = _ctx_with(plan, {1: failed_result})

        ok_result = StepResult(
            failed_step,
            status=StepStatus.DONE,
            tool_result=_tool_result(success=True, output="tuzatildi"),
        )
        retry_ctx = _ctx_with(plan, {1: ok_result})

        llm = _FakeLLM(responses=[_fix_json(description="Boshqacha qayta urinish", n_steps=1)])
        engine, _executors, _verifier_stub = _make_engine(
            llm,
            executor_contexts=[retry_ctx],
            verify_results=[Verification(ok=True, reason="tuzatildi")],
        )

        outcome = await engine.attempt(
            plan=plan,
            ctx=ctx,
            failed_verifications=[(failed_step, Verification(ok=False, reason="x"))],
            trust=TrustLevel.OWNER,
        )

        # Reja to'rt qadamli: [0,1,2,3]; 3 → depends_on [1] (anchor)
        positions = [s.position for s in outcome.extended_plan.steps]
        assert positions == [0, 1, 2, 3]
        new_step = outcome.extended_plan.steps[-1]
        assert new_step.depends_on == [1]
        # Boshqa qadamlar buzilmagan
        assert outcome.extended_plan.steps[2].depends_on == [1]


class TestOrchestratorTransitionsToRecovering:
    """T6 — Orchestrator RECOVERING holatiga o'tadi, keyin DONE."""

    async def test_status_passes_through_recovering(
        self,
        killswitch: KillSwitchState,
        permission_policy: PermissionPolicy,
    ) -> None:
        # State-machine kontraktlari
        assert RunStatus.VERIFYING.can_transition_to(RunStatus.RECOVERING)
        assert RunStatus.RECOVERING.can_transition_to(RunStatus.DONE)
        assert RunStatus.RECOVERING.can_transition_to(RunStatus.FAILED)

        # Stub RecoveryEngine: attempt chaqirilganda record.status ni
        # tekshirishga imkon beradigan callback ishlatamiz.
        seen_status: list[RunStatus] = []
        run_store = RunStore()

        # Yordamchi: shu run_id uchun RecoveryEngine stub
        class _StubRecoveryEngine:
            async def attempt(  # type: ignore[no-untyped-def]
                self, *, plan, ctx, failed_verifications, trust, approved_steps=None
            ):
                # Barcha runlar ichida faqat bittasi bo'ladi
                for record in run_store._runs.values():  # type: ignore[attr-defined]
                    seen_status.append(record.status)
                return RecoveryOutcome(
                    recovered=True,
                    attempts=1,
                    diagnoses=[Diagnosis(root_cause="tuzatildi", fix_steps=[])],
                    extended_plan=plan,
                    final_verification=Verification(ok=True, reason="ok"),
                )

        # Orchestrator o'zgargan qismini sinash uchun __run_plan
        # to'g'ridan-to'g'ri chaqiramiz. Buning uchun asosiy Orchestrator
        # instansini yasab, plan/context'ni qo'lda o'tkazamiz.

        class _FailingVerifier:
            """verify_step: har doim FAIL; verify_run: FAIL umumiy."""

            async def verify_step(self, step, tool_result):  # type: ignore[no-untyped-def]
                return Verification(ok=False, reason="test FAIL")

            def verify_run(self, verifications):  # type: ignore[no-untyped-def]
                return Verification(ok=False, reason="run FAIL")

        # Minimal Orchestrator konstruktori uchun bo'sh registry va
        # boshqa hujjatlar
        from zet.tools.registry import ToolRegistry

        orch = Orchestrator(
            router=None,  # type: ignore[arg-type]
            tool_registry=ToolRegistry(),
            permission_policy=permission_policy,
            approval_service=ApprovalService(),
            killswitch=killswitch,
            run_store=run_store,
            budget_usd=0.10,
            recovery_engine=_StubRecoveryEngine(),  # type: ignore[arg-type]
        )
        # Verifier stub bilan almashtiramiz
        orch._verifier = _FailingVerifier()  # type: ignore[assignment]

        # Fikrlash qadamli reja — executor tool talab qilmaydi va
        # muvaffaqiyatli tugaydi (LLM router yo'q → text=""; ok).
        step = PlanStep(
            position=0,
            description="Fikrla",
            tool_name=None,
            permission_required=PermissionLevel.READ,
        )
        plan = _plan(step)
        record = run_store.create(Command(text="test", channel="cli", trust_level=TrustLevel.OWNER))
        record.plan = plan
        record.steps_total = 1

        result = await orch._run_plan(record, trust=TrustLevel.OWNER, dry_run=False)

        # RecoveryEngine attempt chaqirilganda status RECOVERING bo'lgan
        assert RunStatus.RECOVERING in seen_status
        # Yakuniy holat DONE (stub recovered=True qaytardi)
        assert result.status == RunStatus.DONE


class TestLLMErrorTreatedAsParseError:
    """T7 — LLM istisno recovery ni yiqitmaydi, urinishni yeydi."""

    async def test_llm_error_recorded_as_diagnosis(self) -> None:
        step = _read_step()
        plan = _plan(step)
        failed_result = StepResult(
            step,
            status=StepStatus.FAILED,
            tool_result=_tool_result(success=False, error="x"),
        )
        ctx = _ctx_with(plan, {0: failed_result})

        llm = _FakeLLM(
            responses=[
                LLMError("429 rate limit"),
                LLMError("503 unavailable"),
            ]
        )
        engine, _executors, _verifier_stub = _make_engine(
            llm,
            executor_contexts=[],
            verify_results=[],
        )

        outcome = await engine.attempt(
            plan=plan,
            ctx=ctx,
            failed_verifications=[(step, Verification(ok=False, reason="x"))],
            trust=TrustLevel.OWNER,
        )

        assert outcome.recovered is False
        assert outcome.attempts == 2
        assert len(outcome.diagnoses) == 2
        for diag in outcome.diagnoses:
            assert "llm error" in diag.root_cause.lower()


class TestDiagnosisPromptIncludesContext:
    """T8 — LLM promptida yiqilgan qadam konteksti to'liq ko'rinadi."""

    async def test_prompt_contains_failure_signals(self) -> None:
        step = PlanStep(
            position=0,
            description="Sayt ochish va kontent olish",
            tool_name="test.read",
            permission_required=PermissionLevel.READ,
            expected_outcome="200 OK javob va HTML tanasi",
        )
        plan = _plan(step)

        tool_result = _tool_result(
            success=False,
            output=None,
            error="ConnectionResetError: uzoq javob bermadi",
        )
        ctx = _ctx_with(plan, {0: StepResult(step, tool_result=tool_result)})

        # Retry ctx (ishlatilmaydi, faqat noldan farqli bo'lishi uchun)
        retry_ctx = _ctx_with(plan, {0: StepResult(step, status=StepStatus.DONE)})

        llm = _FakeLLM(responses=[_fix_json()])
        engine, _executors, _verifier_stub = _make_engine(
            llm,
            executor_contexts=[retry_ctx],
            verify_results=[Verification(ok=True, reason="tuzatildi")],
        )

        verification = Verification(ok=False, reason="Tool xato: ConnectionReset")
        await engine.attempt(
            plan=plan,
            ctx=ctx,
            failed_verifications=[(step, verification)],
            trust=TrustLevel.OWNER,
        )

        assert len(llm.calls) == 1
        call = llm.calls[0]
        system_text = call["system"] or ""
        # Sistemada diagnos so'zi va JSON kalitlari
        assert "diagnos" in system_text.lower() or "diagnoz" in system_text.lower()
        assert "root_cause" in system_text
        assert "fix_steps" in system_text
        # Foydalanuvchi promptida qadam tavsifi, kutilgan natija, tool
        # error, verification sababi
        user_content = call["messages"][0].content
        assert step.description in user_content
        assert (step.expected_outcome or "") in user_content
        assert "ConnectionReset" in user_content
        assert verification.reason in user_content
        # Tool output kesilgan (agar bor bo'lsa) DIAGNOSIS_MAX_OUTPUT_CHARS
        # dan uzun bo'lmasligi kerak — bu holatda output None edi.
        assert len(user_content) < DIAGNOSIS_MAX_OUTPUT_CHARS * 2


class TestFixStepsCapped:
    """T9 — 10 ta tuzatish qadami taklif qilinsa faqat DIAGNOSIS_MAX_FIX_STEPS ta olinadi."""

    async def test_capped_at_max(self) -> None:
        assert DIAGNOSIS_MAX_FIX_STEPS == 3

        step = _read_step()
        plan = _plan(step)
        failed_result = StepResult(
            step,
            status=StepStatus.FAILED,
            tool_result=_tool_result(success=False, error="xato"),
        )
        ctx = _ctx_with(plan, {0: failed_result})

        ok_result = StepResult(
            step,
            status=StepStatus.DONE,
            tool_result=_tool_result(success=True, output="ok"),
        )
        retry_ctx = _ctx_with(plan, {0: ok_result})

        llm = _FakeLLM(responses=[_fix_json(n_steps=10)])
        engine, _executors, _verifier_stub = _make_engine(
            llm,
            executor_contexts=[retry_ctx],
            verify_results=[Verification(ok=True, reason="ok")],
        )

        outcome = await engine.attempt(
            plan=plan,
            ctx=ctx,
            failed_verifications=[(step, Verification(ok=False, reason="x"))],
            trust=TrustLevel.OWNER,
        )

        # Asl + cheklangan tuzatish qadamlari
        assert len(outcome.extended_plan.steps) == len(plan.steps) + DIAGNOSIS_MAX_FIX_STEPS
        # Xom LLM javobi to'liq raw'da saqlangan (audit)
        assert len(outcome.diagnoses[0].raw.get("fix_steps", [])) == 10


# ── D1/D2/D3 (KONSOLIDATSIYA v2) — real Executor/PermissionPolicy bilan ──
#
# Yuqoridagi testlar `_FakeExecutor` ishlatadi — u `approved_steps`ni
# umuman tekshirmaydi, faqat chaqiruv argumentlarini yozib qo'yadi. Bu
# D1/D2 uchun YETARLI EMAS: approval-bypass bug'i aynan Executor'ning
# HAQIQIY `policy.check()` darvozasi bilan `approved_steps` o'rtasidagi
# munosabatda edi. Shu sabab quyidagi testlar REAL `Executor` + REAL
# `PermissionPolicy` + REAL `ApprovalService` ishlatadi — soxta emas.


class _AlwaysOkTool(Tool):
    """READ ruxsatli, doim muvaffaqiyatli tool — D2 (autonomous LOW-risk fix)."""

    @property
    def name(self) -> str:
        return "test.read"

    @property
    def description(self) -> str:
        return "test uchun — doim ok"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    async def _execute(self, params: dict[str, Any]) -> Any:
        return {"ok": True}


class _TrackingDeleteTool(Tool):
    """`file.delete` nomli HIGH-risk tool — D1 (approval-bypass) testi uchun.

    NEGA aynan shu nom: `security/permissions.py::HIGH_RISK_TOOLS`da
    hardcoded — Executor'ning eski `policy.check()` metodi buni ko'rib
    permission darajasidan qat'i nazar DOIM tasdiq talab qiladi (V-32).
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "file.delete"

    @property
    def description(self) -> str:
        return "test uchun — HIGH risk, chaqiruvlarni yozib boradi"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"path": {"type": "string"}}}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.WRITE

    async def _execute(self, params: dict[str, Any]) -> Any:
        # MUHIM: shu funksiya chaqirilishi — "fix qadami BAJARILDI"
        # degani. D1 testi buning approval'dan OLDIN hech qachon
        # chaqirilmasligini isbotlaydi.
        self.calls.append(dict(params))
        return {"deleted": True}


def _real_engine(
    llm: _FakeLLM,
    *,
    registry: ToolRegistry,
    policy: PermissionPolicy,
    killswitch: KillSwitchState,
    verifier: _StubVerifier,
    max_retries: int = MAX_RETRIES,
    tool_names: set[str] | None = None,
) -> RecoveryEngine:
    """`_make_engine`dan farqli — soxta emas, HAQIQIY Executor quradi."""

    def factory() -> Executor:
        return Executor(
            registry=registry,
            policy=policy,
            killswitch=killswitch,
            budget_usd=1.0,
            router=None,
        )

    return RecoveryEngine(
        llm_provider=llm,  # type: ignore[arg-type]
        executor_factory=factory,
        verifier=verifier,  # type: ignore[arg-type]
        max_retries=max_retries,
        tool_names=tool_names or {"test.read", "file.delete"},
    )


class TestD1ApprovalBypassPrevention:
    """D1 (KONSOLIDATSIYA v2, MAJBURIY) — HIGH-risk fix qadami Approval
    Engine'ni HECH QACHON chetlab o'tolmaydi.

    Bu — aynan foydalanuvchi talab qilgan "artificial HIGH-risk failure
    → Recovery Engine attempts a fix → verify the Approval Engine is
    invoked and the FIX does not execute until approval arrives" testi.
    """

    async def test_high_risk_fix_raises_and_never_executes_before_approval(
        self,
    ) -> None:
        step = _read_step(position=0)
        plan = _plan(step)
        ctx = _ctx_with(
            plan,
            {
                0: StepResult(
                    step,
                    status=StepStatus.FAILED,
                    tool_result=_tool_result(success=False, error="original xato"),
                )
            },
        )

        # LLM "faylni o'chirish orqali tuzataman" deydi — HIGH risk.
        llm = _FakeLLM(
            responses=[
                _fix_json(
                    tool_name="file.delete",
                    description="Xato faylni o'chirish",
                    expected_outcome="o'chirildi",
                    permission_required="write",
                )
            ]
        )

        registry = ToolRegistry()
        registry.register(_AlwaysOkTool())
        delete_tool = _TrackingDeleteTool()
        registry.register(delete_tool)
        policy = PermissionPolicy()  # default: "file.delete" HIGH_RISK_TOOLS'da
        killswitch = KillSwitchState()
        verifier = _StubVerifier([])  # chaqirilmasligi kerak — quyida tekshiriladi

        engine = _real_engine(
            llm,
            registry=registry,
            policy=policy,
            killswitch=killswitch,
            verifier=verifier,
        )

        with pytest.raises(RecoveryApprovalRequiredError) as exc_info:
            await engine.attempt(
                plan=plan,
                ctx=ctx,
                failed_verifications=[(step, Verification(ok=False, reason="original xato"))],
                trust=TrustLevel.OWNER,
            )

        exc = exc_info.value
        # 1) Aynan HIGH-risk fix qadami approval so'radi
        assert exc.step.tool_name == "file.delete"
        assert exc.decision.needs_approval is True
        assert "Yuqori xavfli" in exc.decision.reason
        # 2) `RecoveryApprovalRequiredError` — Orchestrator'ning `resume()`
        #    keyin TUZATILGAN rejani bajarishi uchun extended_plan yuradi
        assert any(s.tool_name == "file.delete" for s in exc.extended_plan.steps)
        # 3) ENG MUHIM DALIL: fix action HECH QACHON bajarilmadi
        assert delete_tool.calls == [], (
            "D1 BUZILDI: Recovery Engine HIGH-risk fix qadamini "
            "Approval Engine'siz bajarib yubordi"
        )
        # 4) `verify_step` ham chaqirilmadi — chunki executor hatto
        #    fix qadamiga yetguncha to'xtadi
        assert verifier.calls == []

        # ── Approval Engine haqiqatan chaqirilishini/talab qilinishini
        #    tasdiqlaymiz (Orchestrator._handle_approval_required bilan
        #    bir xil zanjir) ────────────────────────────────────────
        approvals = ApprovalService(ttl_minutes=30)
        approval = approvals.request_approval(
            run_id=uuid.uuid4(),
            step_position=exc.step.position,
            reason=exc.decision.reason,
            requested_permission=exc.step.permission_required,
            tool_name=exc.step.tool_name,
            preview={"description": exc.step.description},
        )
        assert approvals.get(approval.id).status == ApprovalStatus.PENDING
        # Approval so'ralgandan keyin ham HALI bajarilmagan
        assert delete_tool.calls == []

        # Ega tasdiqlaguncha FIX bajarilmaydi — endi tasdiqlaymiz va
        # AYNAN shu extended_plan'ni approved_steps bilan qayta ishga
        # tushiramiz (Orchestrator.resume() qiladigan narsa).
        approvals.approve(approval.id)
        retry_executor = Executor(
            registry=registry, policy=policy, killswitch=killswitch, budget_usd=1.0, router=None
        )
        await retry_executor.execute_plan(
            exc.extended_plan,
            approved_steps={exc.step.position},
            trust=TrustLevel.OWNER,
        )
        # 5) Tasdiqdan KEYIN — va faqat keyin — fix haqiqatan bajarildi
        #    (`_fix_json()` `tool_params={}` beradi — bo'sh dict kutiladi)
        assert delete_tool.calls == [{}]


class TestD1OrchestratorLevel:
    """D1 — xuddi shu isbot, lekin `Orchestrator._run_plan()` orqali
    (RECOVERING → AWAITING_APPROVAL, `record.pending_approval_id`,
    real `ApprovalService` qatori) — end-to-end."""

    async def test_orchestrator_pauses_for_approval_not_bypass(
        self,
        killswitch: KillSwitchState,
        permission_policy: PermissionPolicy,
    ) -> None:
        registry = ToolRegistry()
        registry.register(_AlwaysOkTool())
        delete_tool = _TrackingDeleteTool()
        registry.register(delete_tool)

        llm = _FakeLLM(
            responses=[
                _fix_json(
                    tool_name="file.delete",
                    description="Xato holatni o'chirish orqali tuzatish",
                    permission_required="write",
                )
            ]
        )
        engine = _real_engine(
            llm,
            registry=registry,
            policy=permission_policy,
            killswitch=killswitch,
            verifier=_StubVerifier([]),
        )

        class _FailingVerifier:
            """verify_step/verify_run — har doim FAIL (recovery majburan ishga tushsin)."""

            async def verify_step(self, step, tool_result):  # type: ignore[no-untyped-def]
                return Verification(ok=False, reason="test FAIL")

            def verify_run(self, verifications):  # type: ignore[no-untyped-def]
                return Verification(ok=False, reason="run FAIL")

        approvals = ApprovalService()
        run_store = RunStore()
        orch = Orchestrator(
            router=None,  # type: ignore[arg-type]
            tool_registry=registry,
            permission_policy=permission_policy,
            approval_service=approvals,
            killswitch=killswitch,
            run_store=run_store,
            budget_usd=1.0,
            recovery_engine=engine,
        )
        orch._verifier = _FailingVerifier()  # type: ignore[assignment]

        step = PlanStep(
            position=0,
            description="Fikrla",
            tool_name=None,
            permission_required=PermissionLevel.READ,
        )
        plan = _plan(step)
        record = run_store.create(Command(text="test", channel="cli", trust_level=TrustLevel.OWNER))
        record.plan = plan
        record.steps_total = 1

        result = await orch._run_plan(record, trust=TrustLevel.OWNER, dry_run=False)

        # D1: AWAITING_APPROVAL — HECH QACHON DONE/FAILED emas
        assert result.status == RunStatus.AWAITING_APPROVAL
        assert result.pending_approval_id is not None

        pending = approvals.get(result.pending_approval_id)
        assert pending.status == ApprovalStatus.PENDING
        assert pending.tool_name == "file.delete"

        # `record.plan` TUZATILGAN rejaga yangilangan (D1 dizayn talabi —
        # resume() ASL rejani emas, fix qadami bor rejani bajarishi kerak)
        assert len(result.plan.steps) == 2
        assert any(s.tool_name == "file.delete" for s in result.plan.steps)

        # ENG MUHIM: HIGH-risk fix HECH QACHON bajarilmadi
        assert delete_tool.calls == []


class TestD2AutonomousLowRiskFix:
    """D2 (KONSOLIDATSIYA v2) — LOW/MEDIUM-risk fix qadami approval'siz,
    AVTOMATIK bajariladi (real Executor/PermissionPolicy orqali, D1'dagi
    bilan bir xil kod yo'lidan — alohida "avtomatik" tarmoq YO'Q)."""

    async def test_read_permission_fix_executes_without_any_approval(self) -> None:
        step = _read_step(position=0)
        plan = _plan(step)
        ctx = _ctx_with(
            plan,
            {
                0: StepResult(
                    step,
                    status=StepStatus.FAILED,
                    tool_result=_tool_result(success=False, error="original xato"),
                )
            },
        )

        # `_fix_json()` default: tool_name="test.read", permission="read"
        llm = _FakeLLM(responses=[_fix_json()])

        registry = ToolRegistry()
        registry.register(_AlwaysOkTool())
        policy = PermissionPolicy()
        killswitch = KillSwitchState()
        verifier = _StubVerifier([Verification(ok=True, reason="tuzatildi", auto=True)])

        engine = _real_engine(
            llm,
            registry=registry,
            policy=policy,
            killswitch=killswitch,
            verifier=verifier,
        )

        # `approved_steps` UMUMAN berilmagan (None) — shunga qaramay
        # LOW-risk (READ) fix qadami avtomatik bajarilishi kerak.
        outcome = await engine.attempt(
            plan=plan,
            ctx=ctx,
            failed_verifications=[(step, Verification(ok=False, reason="original xato"))],
            trust=TrustLevel.OWNER,
        )

        assert outcome.recovered is True
        assert outcome.attempts == 1


class TestD3AbsoluteRetryCeiling:
    """D3 (KONSOLIDATSIYA v2, MAJBURIY) — `max_retries` argumenti orqali
    ham qattiq shiftdan (`_ABSOLUTE_MAX_RETRIES`) oshib bo'lmaydi.

    Isbot: `max_retries=1000` bilan quriladi, lekin haqiqiy urinishlar
    soni HECH QACHON `_ABSOLUTE_MAX_RETRIES` (5)dan oshmaydi — cheksiz
    retry loop KOD DARAJASIDA imkonsiz, konfiguratsiya bilan chetlab
    o'tib bo'lmaydi."""

    async def test_absolute_ceiling_cannot_be_exceeded(self) -> None:
        from zet.core.recovery import _ABSOLUTE_MAX_RETRIES

        assert _ABSOLUTE_MAX_RETRIES < 1000, "test o'zi ma'nosiz bo'lib qolmasin"

        step = _read_step()
        plan = _plan(step)
        failed_result = StepResult(
            step, status=StepStatus.FAILED, tool_result=_tool_result(success=False, error="x")
        )
        ctx = _ctx_with(plan, {0: failed_result})

        # Har urinish uchun bittadan javob — agar cheklov ishlamasa
        # LLM javoblari darhol tugab `LLMError` ko'tariladi (test buni
        # aniq tutib oladi, garovsiz "aslida ko'proq urinildi" degan
        # noaniqlik qolmasin uchun aynan _ABSOLUTE_MAX_RETRIES ta beramiz).
        llm = _FakeLLM(responses=[_fix_json() for _ in range(_ABSOLUTE_MAX_RETRIES)])

        # Har urinish "hali ham FAIL" deb qaytadigan executor ctx'lari —
        # recovery HECH QACHON erta to'xtamaydi, faqat chegara bilan.
        never_fixed = _ctx_with(
            plan,
            {
                0: StepResult(
                    step,
                    status=StepStatus.FAILED,
                    tool_result=_tool_result(success=False, error="hali ham xato"),
                )
            },
        )
        engine, executors, _verifier = _make_engine(
            llm,
            executor_contexts=[never_fixed for _ in range(_ABSOLUTE_MAX_RETRIES)],
            verify_results=[Verification(ok=False, reason="hali ham xato") for _ in range(_ABSOLUTE_MAX_RETRIES)],
            max_retries=1000,  # KONFIGURATSIYA katta son so'raydi
        )

        outcome = await engine.attempt(
            plan=plan,
            ctx=ctx,
            failed_verifications=[(step, Verification(ok=False, reason="x"))],
            trust=TrustLevel.OWNER,
        )

        assert outcome.recovered is False
        # 1000 EMAS — qattiq shift qancha bo'lsa, shuncha
        assert outcome.attempts == _ABSOLUTE_MAX_RETRIES
        assert len(llm.calls) == _ABSOLUTE_MAX_RETRIES
        assert len(executors) == _ABSOLUTE_MAX_RETRIES

    def test_constructor_clamps_even_smaller_default(self) -> None:
        """Yordamchi birlik test — `__init__` clamp'i to'g'ridan-to'g'ri."""
        from zet.core.recovery import _ABSOLUTE_MAX_RETRIES

        engine, _executors, _verifier = _make_engine(
            _FakeLLM(responses=[]), max_retries=999_999
        )
        assert engine._max_retries == _ABSOLUTE_MAX_RETRIES
