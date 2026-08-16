"""JB-14 PART I/II — TaskGraph real verification + failure classification
intelligent recovery testlari.

AUDIT TOPILMASI (JB-13'da ATAYLAB qoldirilgan, JB-14 endi yopadi):
`TaskGraphExecutor` avval FAQAT `AgentRunResult.success`ga tayanardi
("success=True" ≡ "maqsadga erishildi" — noto'g'ri taxmin) va HAR
qanday xatoni bir xil — "log yoz, `max_retries` marta qayta urin,
keyin FAILED" — deb ko'rardi (kredensial xato bilan tarmoq uzilishi
orasida farq yo'q edi).

Bu testlar HAQIQIY `Verifier`/`failure_classification` bilan (mock
emas) — real `TaskGraphExecutor.run()` orqali — quyidagilarni
isbotlaydi:
    A. EXECUTE + VERIFY → real VERIFIED → DONE.
    B. EXECUTE success + VERIFY FAILED → task DONE emas, mission
       "all_done=False" (spec §8 completion gate).
    C. VERIFICATION_UNCERTAIN + idempotent bo'lmagan tool → keyingi
       `run()` chaqiruvi (mission-level recovery-retry simulyatsiyasi)
       toolni QAYTA CHAQIRMAYDI (ko'r-ko'rona takrorlash yo'q).
    D. `verifier=None` — eski xatti-harakat (NOL regressiya).
    E. TOOL-sinf xatosi + `agent_selector` → muqobil agent bilan
       so'nggi (chegaralangan) urinish, muvaffaqiyat.
    F. AUTHENTICATION-sinf xatosi → retries darhol to'xtaydi (ma'nosiz
       qayta urinish yo'q) — `is_retry_futile` chegarasi.
    G. MODEL-sinf xatosi → `ModelRouter.complete()` (HAQIQIY, mock
       emas) BITTA `run_agent_command()` chaqiruvi ICHIDA muqobil
       providerga o'tadi — SHU BIR task/Mission davom etadi, task-graph
       darajasida hech qanday qayta urinish/klassifikatsiya
       ko'rinmaydi ham (chunki fallback providerdan PASTROQDA,
       shaffof ravishda sodir bo'ladi).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from zet.agents.registry import AgentRegistry
from zet.config import Settings
from zet.core.agent_selector import AgentSelector
from zet.core.mission import Mission, MissionTask
from zet.core.task_graph import TaskGraphExecutor
from zet.core.verifier import VerificationOutcome, Verifier
from zet.domain.agent import AgentSpec
from zet.domain.enums import (
    AgentStatus,
    ModelTier,
    PermissionLevel,
    StepStatus,
)
from zet.llm.base import RateLimitError
from zet.llm.fake import FakeProvider, fake_response
from zet.llm.routed_provider import RoutedLLMProvider
from zet.llm.router import ModelRouter
from zet.security.permissions import PermissionPolicy
from zet.tools.base import Tool, ToolError
from zet.tools.registry import ToolRegistry


class _StubTool(Tool):
    """`test_task_graph.py`dagi bilan bir xil naqsh — mustaqil nusxa."""

    def __init__(
        self,
        name: str,
        *,
        outcomes: list[Any] | None = None,
        idempotent: bool = True,
    ) -> None:
        self._name = name
        self._outcomes = list(outcomes or ["ok"])
        self._idempotent = idempotent
        self.calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "stub"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    @property
    def idempotent(self) -> bool:
        return self._idempotent

    async def _execute(self, params: dict[str, Any]) -> Any:
        self.calls.append(params)
        outcome = self._outcomes.pop(0) if len(self._outcomes) > 1 else self._outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _agent_spec(
    name: str, *, tools: list[str], max_tool_calls: int | None = None
) -> AgentSpec:
    kwargs: dict[str, Any] = {}
    if max_tool_calls is not None:
        kwargs["max_tool_calls"] = max_tool_calls
    return AgentSpec(
        name=name,
        description="test agent",
        system_prompt="test",
        tool_allowlist=tools,
        model_policy=ModelTier.T1_FREE,
        permission_level=PermissionLevel.WRITE,
        **kwargs,
    )


def _mission(*, tasks: list[MissionTask]) -> Mission:
    return Mission(owner_id=uuid.uuid4(), objective="test mission", tasks=tasks)


def _tool_use(name: str, arguments: dict[str, Any] | None = None) -> Any:
    from zet.llm.base import ToolUse

    return ToolUse(id=str(uuid.uuid4()), name=name, arguments=arguments or {})


class TestVerifiedSuccessMarksDone:
    async def test_matching_expected_outcome_verifies_and_completes(self) -> None:
        registry = AgentRegistry()
        registry.register(_agent_spec("agent", tools=["a"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        tools.register(_StubTool("a", outcomes=["natija: 42"]))

        # Ikkinchi javob — agentning YAKUNIY matn javobi (tool
        # chaqiruvidan KEYINGI qadam). `Verifier` `AgentRunResult.output`
        # (agentning o'zi yozgan xulosa)ni tekshiradi, tool'ning xom
        # JSON chiqishini EMAS — shu sabab bu javob "natija"ni o'z
        # ichiga olishi SHART.
        provider = FakeProvider(
            scripted=[
                fake_response(tool_uses=(_tool_use("a"),)),
                fake_response(text="Bajarildi — natija: 42 topildi."),
            ]
        )

        mission = _mission(
            tasks=[
                MissionTask(
                    position=0,
                    title="a",
                    tool="a",
                    agent="agent",
                    expected_outcome="natija",
                )
            ]
        )
        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(auto_approve_write=True, auto_approve_medium=True),
            llm_provider=provider,
            verifier=Verifier(),
            task_timeout_s=5,
        )

        result = await executor.run(mission)

        assert result.all_done is True
        assert result.tasks[0].status == StepStatus.DONE
        assert result.tasks[0].verification_status == VerificationOutcome.VERIFIED.value


class TestVerificationFailureBlocksCompletion:
    async def test_mismatched_expected_outcome_does_not_complete_mission(self) -> None:
        registry = AgentRegistry()
        registry.register(_agent_spec("agent", tools=["a"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        # Tool "success" deb qaytaradi, lekin chiqish kutilgan qisqa
        # shablonni O'Z ICHIGA OLMAYDI — Verifier buni ANIQ rad etadi
        # (qisqa shablon — literal/regex tekshiruv, fail-open YO'Q).
        tools.register(_StubTool("a", outcomes=["mutlaqo boshqa natija"]))

        provider = FakeProvider(
            scripted=[fake_response(tool_uses=(_tool_use("a"),))] * 3
        )

        mission = _mission(
            tasks=[
                MissionTask(
                    position=0,
                    title="a",
                    tool="a",
                    agent="agent",
                    expected_outcome="kod417",  # qisqa shablon — literal qidiriladi
                )
            ]
        )
        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(auto_approve_write=True, auto_approve_medium=True),
            llm_provider=provider,
            verifier=Verifier(),
            max_retries=0,
            task_timeout_s=5,
        )

        result = await executor.run(mission)

        # HAQIQIY DALIL (spec §8 — completion gate): tool "success"
        # qaytargan bo'lsa ham, mission COMPLETED bo'la olmaydi.
        assert result.all_done is False
        assert result.any_failed is True
        assert result.tasks[0].status == StepStatus.FAILED
        assert result.tasks[0].verification_status == VerificationOutcome.VERIFICATION_FAILED.value


class TestVerificationUncertaintyBlocksBlindRetry:
    async def test_uncertain_verification_does_not_reexecute_non_idempotent_tool(self) -> None:
        registry = AgentRegistry()
        registry.register(_agent_spec("agent", tools=["a"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        # `idempotent=False` — yon-samarali tool (masalan xabar yuborish).
        stub = _StubTool("a", outcomes=["ok"], idempotent=False)
        tools.register(stub)

        # Uzun, TAVSIF darajasidagi `expected_outcome` (>3 so'z) va
        # LLM-judge ULANMAGAN (`Verifier()` argumentsiz) — Verifier bu
        # holatda ATAYLAB past-ishonchli fail-open beradi
        # (`confidence=0.6` → `VERIFICATION_UNCERTAIN`, `verifier.py`
        # docstring'iga qarang).
        provider = FakeProvider(scripted=[fake_response(tool_uses=(_tool_use("a"),))])

        mission = _mission(
            tasks=[
                MissionTask(
                    position=0,
                    title="a",
                    tool="a",
                    agent="agent",
                    expected_outcome="xabarni muvaffaqiyatli yuborish va tasdiqlash",
                )
            ]
        )
        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(auto_approve_write=True, auto_approve_medium=True),
            llm_provider=provider,
            verifier=Verifier(),  # LLM-judge YO'Q — fail-open past ishonch
            task_timeout_s=5,
        )

        result = await executor.run(mission)

        assert result.tasks[0].status == StepStatus.FAILED
        assert (
            result.tasks[0].verification_status
            == VerificationOutcome.VERIFICATION_UNCERTAIN.value
        )
        assert len(stub.calls) == 1, "Tool BIR marta chaqirilishi kerak edi"

        # HAQIQIY DALIL: mission-level recovery-retry simulyatsiyasi —
        # `run()` QAYTA chaqiriladi (xuddi `MissionEngine.recover()` dan
        # keyin `_execute_task_graph()` yana chaqirilgani kabi). Tool
        # ko'r-ko'rona QAYTA CHAQIRILMAYDI.
        provider2 = FakeProvider(scripted=[])
        executor2 = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(auto_approve_write=True, auto_approve_medium=True),
            llm_provider=provider2,
            verifier=Verifier(),
            task_timeout_s=5,
        )
        result2 = await executor2.run(mission)

        assert len(stub.calls) == 1, "Uncertain + idempotent-emas tool QAYTA chaqirilmasligi kerak"
        assert result2.tasks[0].status == StepStatus.FAILED


class TestNoVerifierPreservesOldBehavior:
    async def test_success_marks_done_without_verifier(self) -> None:
        registry = AgentRegistry()
        registry.register(_agent_spec("agent", tools=["a"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        tools.register(_StubTool("a", outcomes=["mutlaqo mos kelmaydigan natija"]))

        provider = FakeProvider(scripted=[fake_response(tool_uses=(_tool_use("a"),))])

        mission = _mission(
            tasks=[
                MissionTask(
                    position=0,
                    title="a",
                    tool="a",
                    agent="agent",
                    expected_outcome="hech qachon mos kelmaydigan shablon-417",
                )
            ]
        )
        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(auto_approve_write=True, auto_approve_medium=True),
            llm_provider=provider,
            # verifier berilmagan — eski xatti-harakat.
            task_timeout_s=5,
        )

        result = await executor.run(mission)

        assert result.all_done is True
        assert result.tasks[0].status == StepStatus.DONE
        assert result.tasks[0].verification_status is None


class TestAlternateAgentAfterToolFailure:
    async def test_switches_to_alternate_agent_after_retries_exhausted(self) -> None:
        # MUHIM ARXITEKTURA TOPILMASI (JB-14 audit): `AgentRuntime.run()`
        # o'zining ReAct sikliga ega — bitta tool xatosi ("ToolError")
        # `ToolResult(success=False)`ga aylantirilib SUHBAT kontekstiga
        # qaytariladi va LLM (skript) shu XATONI ko'rib TURIB davom
        # etishga qaror qilishi mumkin (`wants_tools=False` bo'lguncha
        # sikl tugamaydi). Shu sabab "success=False" natijasi FAQAT
        # `AgentRuntime`ning O'Z chegaralaridan biriga (masalan
        # `max_tool_calls`) urilganda yoki kutilmagan istisno yuz
        # berganda qaytadi — alohida "tashqi qayta urinish qatlami" YO'Q.
        #
        # Shu sabab bu test `max_tool_calls=1`dan foydalanadi: birinchi
        # tool chaqiruvi (muvaffaqiyatsiz) sarflanadi, ikkinchi qadamda
        # LLM яna tool so'raganda `AgentMaxToolCallsError` chiqadi —
        # `AgentRuntime.run()` buni ICHKARIDA tutib
        # `AgentRunResult(success=False, error="... tool chaqiruviga
        # yetdi")` qaytaradi. Bu matn `failure_classification.py`da
        # TOOL sifatida tan olinadi (`classify_exception()`dagi
        # `AgentMaxToolCallsError→TOOL` xaritalash bilan izchil).
        registry = AgentRegistry()
        # "a_alt" alifbo bo'yicha "b_main"dan OLDIN keladi —
        # `AgentSelector.assign_tool_agents()` teng qamrovda alifbo
        # bo'yicha tanlaydi (tie-break), shu sabab muqobil sifatida
        # "a_alt" tanlanadi.
        registry.register(_agent_spec("a_alt", tools=["x"]), status=AgentStatus.ACTIVE)
        registry.register(
            _agent_spec("b_main", tools=["x"], max_tool_calls=1), status=AgentStatus.ACTIVE
        )
        tools = ToolRegistry()
        stub = _StubTool("x", outcomes=[ToolError("birinchi xato"), "ok"])
        tools.register(stub)

        provider = FakeProvider(
            scripted=[
                fake_response(tool_uses=(_tool_use("x"),)),  # b_main 1-qadam: tool xato
                fake_response(tool_uses=(_tool_use("x"),)),  # b_main 2-qadam: max_tool_calls
                fake_response(tool_uses=(_tool_use("x"),)),  # a_alt 1-qadam: tool OK
                fake_response(text="Bajarildi."),  # a_alt 2-qadam: yakuniy javob
            ]
        )

        mission = _mission(
            tasks=[MissionTask(position=0, title="x", tool="x", agent="b_main")]
        )
        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(auto_approve_write=True, auto_approve_medium=True),
            llm_provider=provider,
            max_retries=0,
            task_timeout_s=5,
            agent_selector=AgentSelector(registry),
        )

        result = await executor.run(mission)

        assert result.all_done is True
        assert result.tasks[0].status == StepStatus.DONE
        assert result.tasks[0].agent == "a_alt", "Muqobil agentga o'tish kutilgan edi"
        assert result.tasks[0].failure_class == "tool"
        assert len(stub.calls) == 2


class TestAuthenticationFailureStopsRetryEarly:
    async def test_futile_failure_class_does_not_exhaust_retry_budget(self) -> None:
        # `TestAlternateAgentAfterToolFailure`dagi kabi: bitta tool
        # xatosi o'zi `AgentRunResult.success=False` HOSIL QILMAYDI
        # (suhbat kontekstiga qaytariladi, LLM davom etadi). Haqiqiy
        # "butun agent ishga tushishi muvaffaqiyatsiz tugadi" holatini
        # ishonchli hosil qilish uchun IKKINCHI LLM chaqiruvining o'zi
        # (masalan haqiqiy provayder darajasida "invalid api key" bilan
        # rad etilishi) istisno tashlaydi — `AgentRuntime.run()` buni
        # tashqi `except Exception` bilan tutib
        # `AgentRunResult(success=False, error="Kutilmagan xato: ...")`
        # qaytaradi. Bu ikkala qatlamda ham (tool VA provayder) real
        # "401/invalid api key" ko'rinishini beradi.
        registry = AgentRegistry()
        registry.register(_agent_spec("agent", tools=["a"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        stub = _StubTool("a", outcomes=[ToolError("401 unauthorized: invalid api key")])
        tools.register(stub)

        provider = FakeProvider(
            scripted=[
                fake_response(tool_uses=(_tool_use("a"),)),  # 1-qadam: tool→401 xato
                RuntimeError("401 unauthorized: invalid api key"),  # 2-qadam: LLM/provayder o'zi rad etadi
            ]
        )

        mission = _mission(
            tasks=[MissionTask(position=0, title="a", tool="a", agent="agent")]
        )
        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(auto_approve_write=True, auto_approve_medium=True),
            llm_provider=provider,
            max_retries=5,
            task_timeout_s=5,
        )

        result = await executor.run(mission)

        assert result.tasks[0].status == StepStatus.FAILED
        assert result.tasks[0].failure_class == "authentication"
        # HAQIQIY DALIL: `max_retries=5` bo'lsa ham, AUTHENTICATION —
        # qayta urinish ma'nosiz — birinchi (tashqi) urinishdan keyin
        # TO'XTAYDI, tool FAQAT bir marta chaqiriladi.
        assert len(stub.calls) == 1, "AUTHENTICATION xatosi qayta urinilmasligi kerak edi"


def _router_settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        budget_monthly_usd=10.0,
        budget_daily_usd=0.50,
        run_max_usd=0.10,
        tier3_daily_calls=5,
    )


class TestModelFallbackThroughRealRouter:
    async def test_router_fallback_completes_same_task_without_outer_retry(
        self, session: AsyncSession
    ) -> None:
        """G — spec §9 (Model Fallback): asosiy provider (`ollama`,
        `agent.model_policy=T0_LOCAL → TaskClass.SIMPLE` uchun birinchi
        nomzod) `RateLimitError` bilan yiqiladi. `ModelRouter.complete()`
        (HAQIQIY — mock emas, `zet.llm.router`) buni ICHKARIDA tutib
        keyingi nomzodga (`google`) o'tadi — BUTUN bu jarayon bitta
        `run_agent_command()` chaqiruvi ICHIDA, `TaskGraphExecutor`
        hech qanday tashqi qayta urinish/klassifikatsiya qilmasdan
        sodir bo'ladi (`task.retries == 0`, `task.failure_class is
        None` — MUVAFFAQIYAT birinchi tashqi urinishdayoq)."""
        tools = ToolRegistry()
        tools.register(_StubTool("a", outcomes=["ok"]))

        ollama = FakeProvider("ollama", ModelTier.T0_LOCAL, scripted=[RateLimitError("429")])
        google = FakeProvider(
            "google",
            ModelTier.T1_FREE,
            scripted=[
                fake_response(tool_uses=(_tool_use("a"),)),
                fake_response(text="Bajarildi."),
            ],
        )
        router = ModelRouter(
            {"ollama": ollama, "google": google},
            session,
            _router_settings(),
        )

        # T0_LOCAL → `task_class_for_tier()` → `TaskClass.SIMPLE` →
        # `candidates_for(SIMPLE)`ning BIRINCHI nomzodi — aynan "ollama".
        agent_spec_t0 = AgentSpec(
            name="agent",
            description="test agent",
            system_prompt="test",
            tool_allowlist=["a"],
            model_policy=ModelTier.T0_LOCAL,
            permission_level=PermissionLevel.WRITE,
        )
        registry_t0 = AgentRegistry()
        registry_t0.register(agent_spec_t0, status=AgentStatus.ACTIVE)

        mission = _mission(
            tasks=[MissionTask(position=0, title="a", tool="a", agent="agent")]
        )
        executor = TaskGraphExecutor(
            agent_registry=registry_t0,
            tool_registry=tools,
            permission_policy=PermissionPolicy(auto_approve_write=True, auto_approve_medium=True),
            llm_provider=RoutedLLMProvider(router),
            task_timeout_s=5,
        )

        result = await executor.run(mission)

        assert result.all_done is True
        assert result.tasks[0].status == StepStatus.DONE
        # HAQIQIY DALIL: fallback providerning ICHIDA sodir bo'lgani —
        # tashqi TaskGraph darajasida HECH qanday qayta urinish yoki
        # muvaffaqiyatsizlik klassifikatsiyasi ko'rinmadi.
        assert result.tasks[0].retries == 0
        assert result.tasks[0].failure_class is None
        # E'TIBOR: `ollama`ning YAGONA skriptlangan xatosi circuit
        # breaker chegarasidan (`BREAKER_THRESHOLD=3`) PASTDA — shu
        # sabab agentning IKKINCHI LLM qadamida `ModelRouter` yana
        # ollama'ni BIRINCHI nomzod sifatida sinaydi (bu safar
        # muvaffaqiyatli — skript bo'sh, standart echo javob).
        # `google` FAQAT bitta (birinchi, tool-chaqiruv) qadam uchun
        # ishlatildi. Bu HAQIQIY, kutilgan xatti-harakat — muhim DALIL
        # shundaki, TaskGraph darajasida bironta ham qayta
        # urinish/klassifikatsiya SODIR BO'LMADI (`retries == 0`,
        # `failure_class is None`) — fallback butunlay Router ICHIDA
        # yutildi.
        assert len(ollama.calls) == 2
        assert len(google.calls) == 1
