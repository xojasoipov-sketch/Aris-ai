"""World State testlari (JB-3).

Audit topilmasi: birlashtirilgan holat modeli umuman yo'q edi va
ContextEngine topgan kontekst hech qanday LLM promptiga yetmasdi.

Bu testlar ikki narsani qulflaydi:
    1. HALOL HOLAT — o'qib bo'lmagan manba BO'SH deb ko'rsatilmaydi,
       `unavailable`ga tushadi va promptda ochiq aytiladi.
    2. FAIL-OPEN — bitta manba yiqilsa qolganlari baribir to'planadi,
       butun blok yiqilsa run to'xtamaydi.
"""

from __future__ import annotations

from typing import Any

from zet.core.world_state import WorldState, WorldStateBuilder, build_world_state_text
from zet.domain.enums import AgentStatus, MissionStatus


class _Boom:
    """Har qanday CHAQIRUVDA yiqiladigan soxta manba.

    Atribut olishda emas, aynan chaqirishda yiqiladi — haqiqiy nosozlik
    (DB uzilishi) shunday ko'rinadi: obyekt bor, so'rov yiqiladi.
    """

    def __getattr__(self, name: str) -> Any:
        def _fail(*_args: Any, **_kwargs: Any) -> Any:
            # Sinxron otiladi — `await source.method()` da ham xato
            # `await`gacha ko'tariladi, ya'ni sync va async chaqiruvlar
            # uchun bir xil ishlaydi va osilgan korutina qoldirmaydi.
            raise RuntimeError(f"manba yiqildi: {name}")

        return _fail


class _Task:
    def __init__(self, title: str) -> None:
        self.title = title


class _Project:
    def __init__(self, name: str) -> None:
        self.name = name


class _Workspace:
    def __init__(self, *, tasks: list[_Task], projects: list[_Project]) -> None:
        self._tasks = tasks
        self._projects = projects

    async def list_tasks(self, **_: Any) -> list[_Task]:
        return self._tasks

    async def list_projects(self, **_: Any) -> list[_Project]:
        return self._projects


class _Mission:
    def __init__(self, objective: str, status: MissionStatus) -> None:
        self.objective = objective
        self.status = status


class _MissionRepo:
    def __init__(self, missions: list[_Mission]) -> None:
        self._missions = missions

    async def list(self, **_: Any) -> list[_Mission]:
        return self._missions


class _AgentSpec:
    def __init__(self, name: str) -> None:
        self.name = name


class _AgentState:
    def __init__(self, name: str, *, status: AgentStatus, runs: int, failed: int) -> None:
        self.spec = _AgentSpec(name)
        self.status = status
        self.total_runs = runs
        self.failed_runs = failed


class _AgentRegistry:
    def __init__(self, states: list[_AgentState]) -> None:
        self._states = states

    def list_agents(self, **_: Any) -> list[_AgentState]:
        return self._states


class _Approvals:
    def __init__(self, count: int) -> None:
        self._count = count

    def all_pending(self) -> list[object]:
        return [object()] * self._count


class _Snapshot:
    spent_today_usd = 2.10
    remaining_month_usd = 7.90


async def _snapshot() -> _Snapshot:
    return _Snapshot()


class TestBuild:
    async def test_collects_all_sources(self) -> None:
        builder = WorldStateBuilder(
            agent_registry=_AgentRegistry(
                [
                    _AgentState("ceo", status=AgentStatus.ACTIVE, runs=10, failed=0),
                    _AgentState("smm", status=AgentStatus.ACTIVE, runs=4, failed=3),
                ]
            ),
            approvals=_Approvals(2),
            workspace=_Workspace(
                tasks=[_Task("Hisobot yoz"), _Task("Mijozga javob ber")],
                projects=[_Project("Do'kon")],
            ),
            mission_repo=_MissionRepo(
                [
                    _Mission("biznesni tekshir", MissionStatus.EXECUTING),
                    _Mission("eski ish", MissionStatus.COMPLETED),
                ]
            ),
            budget_snapshot=_snapshot,
        )

        state = await builder.build()

        assert state.open_tasks == 2
        assert state.task_titles == ["Hisobot yoz", "Mijozga javob ber"]
        assert state.active_projects == 1
        assert state.project_names == ["Do'kon"]
        # Faqat terminal BO'LMAGAN mission hisoblanadi.
        assert state.active_missions == 1
        assert state.pending_approvals == 2
        assert state.active_agents == 2
        # Yarmidan ko'pi yiqilgan agent muammoli deb belgilanadi.
        assert state.unhealthy_agents == ["smm"]
        assert state.budget_spent_today_usd == 2.10
        assert state.unavailable == []

    async def test_healthy_agent_with_one_failure_is_not_flagged(self) -> None:
        """Bitta yiqilishdan shovqin qilmaymiz — faqat barqaror muammo."""
        builder = WorldStateBuilder(
            agent_registry=_AgentRegistry(
                [_AgentState("ceo", status=AgentStatus.ACTIVE, runs=10, failed=1)]
            )
        )

        state = await builder.build()

        assert state.unhealthy_agents == []

    async def test_missing_sources_stay_empty_without_lying(self) -> None:
        """Manba berilmagan bo'lsa — nol, lekin `unavailable`da EMAS."""
        state = await WorldStateBuilder().build()

        assert state.open_tasks == 0
        assert state.budget_spent_today_usd is None  # nol EMAS — noma'lum
        assert state.unavailable == []


class TestHonestState:
    async def test_broken_source_is_reported_not_hidden(self) -> None:
        """O'qib bo'lmagan manba BO'SH deb ko'rsatilmaydi (halol holat)."""
        builder = WorldStateBuilder(
            workspace=_Boom(),
            approvals=_Boom(),
            budget_snapshot=_Boom().snapshot,
        )

        state = await builder.build()

        assert "vazifalar" in state.unavailable
        assert "loyihalar" in state.unavailable
        assert "kutilayotgan tasdiqlar" in state.unavailable

    async def test_one_broken_source_does_not_stop_the_rest(self) -> None:
        """Fail-open: yiqilgan manba qolganlarini to'sib qo'ymaydi."""
        builder = WorldStateBuilder(
            workspace=_Boom(),
            approvals=_Approvals(3),
        )

        state = await builder.build()

        assert state.pending_approvals == 3
        assert "vazifalar" in state.unavailable

    def test_prompt_warns_model_not_to_claim_unknown(self) -> None:
        state = WorldState(unavailable=["vazifalar"])

        block = state.to_prompt_block()

        assert "O'QIB BO'LMADI" in block
        assert "DA'VO QILMA" in block


class TestPromptBlock:
    def test_empty_state_produces_no_block(self) -> None:
        """Hech narsa yo'q bo'lsa — bo'sh matn (keraksiz token sarflamaymiz)."""
        assert WorldState().to_prompt_block() == ""

    def test_counts_and_examples_are_rendered(self) -> None:
        state = WorldState(
            open_tasks=3,
            task_titles=["Hisobot", "Qo'ng'iroq"],
            active_projects=1,
            project_names=["Do'kon"],
            pending_approvals=1,
            budget_spent_today_usd=2.1,
            budget_remaining_month_usd=7.9,
        )

        block = state.to_prompt_block()

        assert "Ochiq vazifalar: 3" in block
        assert "Hisobot" in block
        assert "Faol loyihalar: 1" in block
        assert "Tasdiq kutayotgan amallar: 1" in block
        assert "$2.10" in block and "$7.90" in block

    def test_killswitch_is_stated_first(self) -> None:
        block = WorldState(killswitch_engaged=True, open_tasks=5).to_prompt_block()

        lines = block.splitlines()
        assert "FAVQULODDA TO'XTATISH" in lines[1]


class TestBuildText:
    async def test_total_failure_returns_empty_string(self) -> None:
        """Blok majburiy emas — qurish yiqilsa run to'xtamaydi."""

        class _BrokenBuilder:
            async def build(self) -> WorldState:
                raise RuntimeError("hammasi yiqildi")

        text = await build_world_state_text(_BrokenBuilder())  # type: ignore[arg-type]

        assert text == ""

    async def test_returns_prompt_block_on_success(self) -> None:
        builder = WorldStateBuilder(approvals=_Approvals(1))

        text = await build_world_state_text(builder)

        assert "Tasdiq kutayotgan amallar: 1" in text


class TestContextKeywords:
    def test_context_now_reaches_capability_search(self) -> None:
        """JB-3: ilgari `del context` bilan tashlanardi — endi ishlatiladi."""
        from zet.core.mission_orchestrator import _context_keywords

        words = _context_keywords(
            {
                "fragments": [
                    {"source": "memory", "content": "Do'kon loyihasi haqida eslatma"},
                ]
            }
        )

        assert "loyihasi" in words
        # Qisqa so'zlar (<4 harf) shovqin — tashlanadi.
        assert all(len(w) >= 4 for w in words)

    def test_broken_context_shape_is_ignored(self) -> None:
        from zet.core.mission_orchestrator import _context_keywords

        assert _context_keywords({}) == []
        assert _context_keywords({"fragments": "buzuq"}) == []

    def test_keyword_count_is_capped(self) -> None:
        """Uzun kontekst qidiruvni ma'nosizlantirmasin."""
        from zet.core.mission_orchestrator import _CONTEXT_KEYWORD_LIMIT, _context_keywords

        content = " ".join(f"sozlar{i}" for i in range(50))
        words = _context_keywords({"fragments": [{"source": "m", "content": content}]})

        assert len(words) == _CONTEXT_KEYWORD_LIMIT


class TestOrchestratorWiring:
    async def test_provider_failure_does_not_break_run(self) -> None:
        """Provider yiqilsa Orchestrator bo'sh blok bilan davom etadi."""
        from zet.core.orchestrator import Orchestrator

        async def _broken() -> str:
            raise RuntimeError("world state yiqildi")

        orchestrator = Orchestrator.__new__(Orchestrator)  # ctor'siz, faqat metod
        orchestrator._world_state_provider = _broken  # type: ignore[attr-defined]

        assert await orchestrator._collect_world_state() == ""

    async def test_no_provider_returns_empty(self) -> None:
        from zet.core.orchestrator import Orchestrator

        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator._world_state_provider = None  # type: ignore[attr-defined]

        assert await orchestrator._collect_world_state() == ""


class TestPromptInjectionPoints:
    def test_answer_prompt_includes_world_state(self) -> None:
        from zet.prompts.answer import build_answer_prompt

        prompt = build_answer_prompt(
            "bugun nima muhim?",
            step_description="javob yoz",
            world_state="HOZIRGI HOLAT:\n- Ochiq vazifalar: 2",
        )

        assert "Ochiq vazifalar: 2" in prompt

    def test_answer_prompt_without_world_state_is_unchanged(self) -> None:
        from zet.prompts.answer import build_answer_prompt

        prompt = build_answer_prompt("salom", step_description="javob yoz")

        assert "HOZIRGI HOLAT" not in prompt
