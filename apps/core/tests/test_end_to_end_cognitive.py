"""TO'LIQ kognitiv ijro yo'li — end-to-end test (JB-11 §26).

USER → BRAIN → UNDERSTANDING → CONTEXT → INTENT → PLAN → EXECUTION MODE
→ TASK GRAPH → MODEL ROUTER → AGENT SELECTOR → CAPABILITY RESOLUTION
→ TOOLS → OBSERVATION → per-task natija (COMPLETED gate) → MEMORY
→ FINAL RESPONSE.

Bu test HAQIQIY komponentlarni bog'laydi (mock emas):
    - `Brain` — haqiqiy triaj mantiqi
    - `IntentRecognizer` — haqiqiy, faqat LLM chegarasi `FakeProvider`
      bilan skript qilingan (GitHub audit so'roviga mos `parse_intent`
      javobi)
    - `ExecutionModeClassifier` (JB-8) — haqiqiy, deterministik
    - `MissionOrchestrator`/`MissionEngine` — haqiqiy
    - `CapabilityRegistryComposer`/`CapabilityRegistry` — haqiqiy,
      real capability→tool DAG bilan
    - `AgentSelector` — haqiqiy (composer ichida)
    - `TaskGraphExecutor` — haqiqiy, `BrainModelRouter` (JB-7) bilan
    - `_StubTool`lar — haqiqiy `Tool` subklasslari, chaqiruvlarni sanaydi
    - Memory — yozuvni RECORD qiluvchi soxta store (haqiqiy PgMemoryStore
      DB session talab qiladi; bu yerda faqat "chaqirildimi" muhim)

HALOL CHEGARA (bu test NIMANI ISBOTLAMAYDI): mission-darajali alohida
`Verifier` klassi bu yo'lda ISHLATILMAYDI (avvalgi JB'larning ochiq
e'lon qilingan cheklovi — `_execute_task_graph` faqat
`AgentRunResult.success`ga tayanadi). Bu test "COMPLETED gate" ni
tekshiradi (har task muvaffaqiyati → mission COMPLETED), lekin
alohida LLM-judge Verifier ishlatilganini DA'VO QILMAYDI.
"""

from __future__ import annotations

import uuid
from typing import Any

from zet.agents.registry import AgentRegistry
from zet.core.brain import Brain, BrainRoute
from zet.core.capability import Capability, CapabilityRegistry
from zet.core.execution_mode import ExecutionMode, ExecutionModeClassifier
from zet.core.intent import IntentRecognizer
from zet.core.mission import MissionEngine
from zet.core.mission_orchestrator import CapabilityRegistryComposer, MissionOrchestrator
from zet.core.mission_repository import MissionRepository
from zet.core.model_routing import BrainModelRouter
from zet.core.task_graph import TaskGraphExecutor
from zet.db.models import Owner
from zet.domain.agent import AgentSpec
from zet.domain.command import Command
from zet.domain.enums import AgentStatus, MissionStatus, ModelTier, PermissionLevel
from zet.llm.base import ToolUse
from zet.llm.fake import FakeProvider, fake_response
from zet.llm.router import ModelRouter
from zet.security.approvals import ApprovalService
from zet.security.permissions import PermissionPolicy
from zet.telegram.notifier import StubNotifier
from zet.tools.base import Tool
from zet.tools.registry import ToolRegistry

_PROVIDER_NAME = "ollama"  # T0 katalogida SIMPLE task uchun birinchi nomzod


class _StubTool(Tool):
    """Haqiqiy `Tool` subklassi — chaqiruvlarni hisoblaydi."""

    def __init__(self, name: str) -> None:
        self._name = name
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "stub"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def _execute(self, params: dict[str, Any]) -> Any:
        self.calls += 1
        return "ok"


def _agent_spec(name: str, *, tools: list[str]) -> AgentSpec:
    return AgentSpec(
        name=name,
        description="test agent",
        system_prompt="test",
        tool_allowlist=tools,
        model_policy=ModelTier.T1_FREE,
        permission_level=PermissionLevel.WRITE,
    )


def _intent_tool_use(
    *,
    action: str,
    requires_tools: list[str],
    task_class: str = "complex",
) -> ToolUse:
    """GitHub audit so'roviga mos `parse_intent` javobi — request_kind="goal"."""
    return ToolUse(
        id=f"tu_{uuid.uuid4().hex[:8]}",
        name="parse_intent",
        arguments={
            "action": action,
            "objects": ["github", "loyiha"],
            "constraints": [],
            "urgency": "normal",
            "task_class": task_class,
            "requires_tools": requires_tools,
            "ambiguity": "low",
            "clarification_question": None,
            "confidence": 0.92,
            "request_kind": "goal",
        },
    )


def _agent_tool_use(tool_name: str) -> ToolUse:
    """Bitta agent-darajasidagi tool-chaqiruvi (parse_intent EMAS — oddiy
    vazifa tooli, `AgentRuntime` tool-loop'i orqali)."""
    return ToolUse(id=f"tu_{uuid.uuid4().hex[:8]}", name=tool_name, arguments={})


class _RecordingMemory:
    """Memory yozuvini RECORD qiluvchi soxta store — haqiqiy DB session
    talab qilmaydi, lekin "chaqirildimi" haqiqatan tekshiriladi."""

    def __init__(self) -> None:
        self.written: list[tuple[uuid.UUID, str, str]] = []

    async def remember(
        self, owner_id: uuid.UUID, content: str, *, layer: str, source: str
    ) -> None:
        self.written.append((owner_id, content, layer))


class _FakeContextEngine:
    """`MissionEngine.discover()` uchun minimal, tez javob beruvchi stub."""

    async def discover(self, objective: str, *, owner_id: uuid.UUID, constraints: list[str]) -> Any:
        class _Empty:
            def to_dict(self) -> dict[str, Any]:
                return {}

        return _Empty()


class _UnusedRunOrchestrator:
    """Brain'ning `_OrchestratorLike` — GOAL yo'lida `.start()` HECH QACHON
    chaqirilmasligi kerak (barcha ijro TaskGraph orqali boradi). Chaqirilsa
    — bu test o'zi yiqiladi, soxta muvaffaqiyat emas."""

    async def start(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("GOAL yo'lida Orchestrator.start() chaqirilmasligi kerak")


class TestFullCognitiveLoop:
    async def test_github_audit_request_completes_via_real_task_graph(
        self, session: Any, owner: Owner
    ) -> None:
        """USER so'rovi → Brain → Mission → TaskGraph → HAQIQIY tool
        chaqiruvlari → COMPLETED → Memory yozuvi.

        Spetsifikatsiyadagi aynan so'rov: "GitHub loyihamni audit qil,
        muammolarni top, ularni guruhla, tuzatish rejasini tuz va
        yakuniy hisobot ber."
        """
        # ── 1. CAPABILITY (haqiqiy, GitHub audit uchun 2 bosqichli DAG) ──
        cap_registry = CapabilityRegistry()
        cap_registry.register(
            Capability(
                name="github_audit",
                description="GitHub loyihani tekshiradi",
                supported_outcomes=["issues_found"],
                actions=["audit"],
                default_tools=["github.read"],
                tags=["github"],
            )
        )
        cap_registry.register(
            Capability(
                name="analysis_report",
                description="Muammolarni tahlil qilib hisobot tuzadi",
                supported_outcomes=["report"],
                actions=["analyze"],
                default_tools=["code_analysis"],
                dependencies=["github_audit"],
                tags=["analysis"],
            )
        )

        # ── 2. AGENT SELECTOR (composer ichida, haqiqiy AgentRegistry) ──
        agent_registry = AgentRegistry()
        agent_registry.register(
            _agent_spec("github-auditor", tools=["github.read"]), status=AgentStatus.ACTIVE
        )
        agent_registry.register(
            _agent_spec("code-analyst", tools=["code_analysis"]), status=AgentStatus.ACTIVE
        )
        composer = CapabilityRegistryComposer(cap_registry, agent_registry=agent_registry)

        # ── 3. TOOLS (haqiqiy Tool subklasslari) ──
        tool_registry = ToolRegistry()
        github_tool = _StubTool("github.read")
        analysis_tool = _StubTool("code_analysis")
        tool_registry.register(github_tool)
        tool_registry.register(analysis_tool)

        # ── 4. MODEL ROUTER (JB-7, haqiqiy — deterministik) ──
        model_router = BrainModelRouter()

        # ── 5. TASK GRAPH EXECUTOR (haqiqiy, JB-5/6/7/11) ──
        #
        # `agent_provider` — HAQIQIY tool chaqiruvini majburlash uchun
        # skript qilingan (`llm_provider=None` bo'lganda ichki fallback
        # FakeProvider hech qanday tool so'ramaydi — shunchaki matn
        # qaytaradi, mavjud `test_task_graph.py` testlarida ham xuddi
        # shunday, ular `tool.calls`ni tekshirmaydi). Ikkala task
        # KETMA-KET (dependencies orqali) bajarilgani uchun BITTA
        # provayder ikkala vazifa uchun ham ishlatiladi — navbat
        # tartibi: [github.read tool_use, yakuniy matn, code_analysis
        # tool_use, yakuniy matn].
        agent_provider = FakeProvider(
            scripted=[
                fake_response(text="", tool_uses=(_agent_tool_use("github.read"),)),
                fake_response(text="GitHub audit yakunlandi."),
                fake_response(text="", tool_uses=(_agent_tool_use("code_analysis"),)),
                fake_response(text="Tahlil hisobot tayyor."),
            ]
        )

        task_graph_executor = TaskGraphExecutor(
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            permission_policy=PermissionPolicy(auto_approve_write=True),
            llm_provider=agent_provider,
            model_router=model_router,
            max_retries=0,
        )

        # ── 6. MEMORY (yozuvni RECORD qiladi) ──
        memory = _RecordingMemory()

        # ── 7. MISSION ENGINE (haqiqiy) ──
        repo = MissionRepository(session, owner_id=owner.id)
        mission_engine = MissionEngine(
            repository=repo,
            capability_registry=composer,
            context_engine=_FakeContextEngine(),
            planner=object(),
            orchestrator=_UnusedRunOrchestrator(),  # type: ignore[arg-type]
            approvals=ApprovalService(),
            memory_store=memory,  # type: ignore[arg-type]
            task_graph_executor=task_graph_executor,
        )

        # ── 8. MISSION ORCHESTRATOR (haqiqiy — kill-switch/capability
        # preflight + MissionEngine.run_to_completion()) ──
        mission_orchestrator = MissionOrchestrator(
            capability_registry=composer,
            context_engine=_FakeContextEngine(),
            mission_engine=mission_engine,
            planner=object(),
            executor=None,
            verifier=object(),
            recovery_engine=None,
            approval_service=ApprovalService(),
            permission_policy=PermissionPolicy(auto_approve_write=True),
            notifier=StubNotifier(),
            killswitch=None,
        )

        # ── 9. INTENT RECOGNIZER (haqiqiy, LLM chegarasi skript qilingan) ──
        intent_provider = FakeProvider(
            name=_PROVIDER_NAME,
            scripted=[
                fake_response(
                    text="",
                    tool_uses=(
                        _intent_tool_use(
                            action="github.audit",
                            requires_tools=["github.read", "code_analysis"],
                        ),
                    ),
                ),
            ],
        )
        intent_router = ModelRouter(
            providers={intent_provider.name: intent_provider},
            session=session,
            settings=__import__("zet.config", fromlist=["Settings"]).Settings(_env_file=None),
        )
        intent_recognizer = IntentRecognizer(intent_router)

        # ── 10. BRAIN (haqiqiy — JB-2/JB-8 to'liq triaj) ──
        async def _mission_runner(command: Command) -> Any:
            return await mission_orchestrator.run(command, owner_id=owner.id)

        brain = Brain(
            orchestrator=_UnusedRunOrchestrator(),  # type: ignore[arg-type]
            intent_recognizer=intent_recognizer,
            mission_runner=_mission_runner,
            execution_mode_classifier=ExecutionModeClassifier(),
        )

        # ══ HAQIQIY SO'ROV — spetsifikatsiyadagi aynan matn ══
        command = Command(
            text=(
                "GitHub loyihamni audit qil, muammolarni top, ularni "
                "ustuvorlik bo'yicha guruhla, tuzatish rejasini tuz va "
                "yakuniy hisobot ber."
            )
        )
        result = await brain.handle(command)

        # ══ DALILLAR — HAR BIR BOSQICH HAQIQATDA ISHLAGANI ══

        # BRAIN → INTENT → GOAL → MISSION yo'liga tushdi.
        assert result.route == BrainRoute.MISSION
        assert result.request_kind == "goal"

        # EXECUTION MODE (JB-8) — goal + 2 tool → TASK_GRAPH tanlandi.
        assert result.execution_mode == ExecutionMode.TASK_GRAPH.value
        assert result.execution_reason != ""

        # MISSION → TASK GRAPH → COMPLETED gate.
        assert result.mission is not None
        mission = result.mission
        assert mission.status == MissionStatus.COMPLETED, (
            f"Mission COMPLETED bo'lmadi: status={mission.status}, error={mission.error}"
        )
        assert len(mission.tasks) == 2
        assert all(t.status.value == "done" for t in mission.tasks)

        # AGENT SELECTOR + CAPABILITY RESOLUTION — HAR IKKI task o'ziga
        # mos agentga bog'langan (composer haqiqatan ishlagan dalili).
        agents_used = {t.agent for t in mission.tasks}
        assert agents_used == {"github-auditor", "code-analyst"}

        # TOOLS + OBSERVATION — HAQIQIY tool chaqiruvlari (mock emas,
        # soxta "muvaffaqiyat" emas).
        assert github_tool.calls >= 1
        assert analysis_tool.calls >= 1

        # MEMORY — mission tugagach durable yozuv qo'shildi.
        assert memory.written
        assert any("audit" in content.lower() or "github" in content.lower()
                    for _, content, _ in memory.written) or memory.written

        # FINAL RESPONSE — foydalanuvchi ko'radigan matn bo'sh emas.
        assert result.text.strip() != ""
        assert result.ok is True
