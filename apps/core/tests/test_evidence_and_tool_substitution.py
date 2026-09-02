"""JB-15 PART I/II — real-world evidence + tool intelligence testlari.

AUDIT TOPILMASI (JB-14'da ATAYLAB qoldirilgan, JB-15 endi yopadi):
    1. `TaskGraphExecutor._verify_task_result()` (JB-14) FAQAT agentning
       O'Z matn xulosasini tekshirardi — tool'ning haqiqiy strukturaviy
       natijasi (masalan `{"path": "...", "size_bytes": 128}`) UMUMAN
       ko'rilmasdi. Tashqi DUNYO holati hech qachon so'ralmasdi.
    2. TOOL-sinf xatosidan keyin FAQAT muqobil AGENT tanlanardi — muqobil
       TOOL degan tushuncha umuman yo'q edi.

Bu testlar HAQIQIY `EvidenceProvider`/`ToolSubstitutionResolver` bilan
(mock emas) — real `TaskGraphExecutor.run()` orqali — quyidagilarni
isbotlaydi:
    A. Fayl yaratish → HAQIQIY fayl tizimi → VERIFIED.
    C. GitHub issue → GitHubReadTool orqali (stub rejimda, tarmoqsiz,
       LEKIN haqiqiy kod yo'li) — VERIFIED/NOT_FOUND.
    D. Telegram xabar → message_id-asoslangan dalil.
    E. Instagram post → WRITE→GET namunasi (recent_media).
    F. Tool xatosi → muqobil MOS tool (real TaskGraph orqali).
    G. Muqobil MOS EMAS (ruxsat/xavf farq qiladi) → ISHLATILMAYDI.
    H. Muqobil tool topilmasa → muqobil AGENT (JB-14) hamon ishlaydi.
    I. Tashqi noaniqlik (evidence UNKNOWN) → ko'r-ko'rona qayta urinish YO'Q.
    J. Killswitch → muqobil tool SINALMAYDI ham.
    K. Ruxsat — resolver past ruxsatli chaqiruvchiga yuqori ruxsatli
       muqobilni bermaydi.
    L. Approval — yuqori xavfli muqobil AVTOMATIK bypass qilinmaydi
       (mavjud fail-closed approval gate, JB-14'dagi bilan bir xil
       tamoyil — "kutish" emas, xavfsiz rad etish).
    M. To'liq tsikl — evidence + tool substitution BIRGA.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from zet.agents.registry import AgentRegistry
from zet.core.evidence import (
    CameraEvidenceProvider,
    EvidenceProviderRegistry,
    EvidenceState,
    FilesystemEvidenceProvider,
    GitHubEvidenceProvider,
    InstagramEvidenceProvider,
    TelegramEvidenceProvider,
)
from zet.core.mission import Mission, MissionTask
from zet.core.task_graph import TaskGraphExecutor
from zet.core.tool_substitution import ToolSubstitutionResolver
from zet.domain.enums import AgentStatus, ModelTier, PermissionLevel, RiskLevel, StepStatus
from zet.llm.fake import FakeProvider, fake_response
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.tools.base import Tool, ToolError
from zet.tools.builtin.github import GitHubReadTool, GitHubWriteTool
from zet.tools.builtin.note_write import NoteWriteTool
from zet.tools.registry import ToolRegistry


class _StubTool(Tool):
    """`test_task_graph_verification_and_recovery.py`dagi bilan bir xil
    naqsh — JB-15 uchun `capability_tag`/`risk_level` konfiguratsiyasi
    bilan kengaytirilgan mustaqil nusxa."""

    def __init__(
        self,
        name: str,
        *,
        outcomes: list[Any] | None = None,
        idempotent: bool = True,
        capability_tag: str | None = None,
        permission_level: PermissionLevel = PermissionLevel.WRITE,
        risk_level: RiskLevel = RiskLevel.LOW,
    ) -> None:
        self._name = name
        self._outcomes = list(outcomes or ["ok"])
        self._idempotent = idempotent
        self._capability_tag = capability_tag
        self._permission_level = permission_level
        self._risk_level = risk_level
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
    def permission_level(self) -> PermissionLevel:
        return self._permission_level

    @property
    def risk_level(self) -> RiskLevel:
        return self._risk_level

    @property
    def idempotent(self) -> bool:
        return self._idempotent

    @property
    def capability_tag(self) -> str | None:
        return self._capability_tag

    async def _execute(self, params: dict[str, Any]) -> Any:
        self.calls.append(params)
        outcome = self._outcomes.pop(0) if len(self._outcomes) > 1 else self._outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _agent_spec(
    name: str,
    *,
    tools: list[str],
    permission_level: PermissionLevel = PermissionLevel.WRITE,
    max_tool_calls: int | None = None,
) -> Any:
    from zet.domain.agent import AgentSpec

    kwargs: dict[str, Any] = {}
    if max_tool_calls is not None:
        kwargs["max_tool_calls"] = max_tool_calls
    return AgentSpec(
        name=name,
        description="test agent",
        system_prompt="test",
        tool_allowlist=tools,
        model_policy=ModelTier.T1_FREE,
        permission_level=permission_level,
        **kwargs,
    )


def _mission(*, tasks: list[MissionTask]) -> Mission:
    return Mission(owner_id=uuid.uuid4(), objective="test mission", tasks=tasks)


def _tool_use(name: str, arguments: dict[str, Any] | None = None) -> Any:
    from zet.llm.base import ToolUse

    return ToolUse(id=str(uuid.uuid4()), name=name, arguments=arguments or {})


# ── A. Filesystem — HAQIQIY fayl tizimi (spec §2, §18.A) ─────────────


class TestFilesystemEvidenceEndToEnd:
    async def test_note_write_verified_against_real_filesystem(self, tmp_path: Path) -> None:
        """`note.write` HAQIQIY vault papkasiga yozadi — `Verifier`
        emas, `FilesystemEvidenceProvider` `pathlib.Path.is_file()`
        bilan HAQIQIY tekshiradi (agentning "yaratdim" degan so'ziga
        emas)."""
        registry = AgentRegistry()
        registry.register(_agent_spec("agent", tools=["note.write"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        tools.register(NoteWriteTool(notes_dir=tmp_path))

        provider = FakeProvider(
            scripted=[
                fake_response(
                    tool_uses=(_tool_use("note.write", {"title": "hisobot", "content": "salom"}),)
                ),
                fake_response(text="Eslatma yozildi."),
            ]
        )
        evidence_registry = EvidenceProviderRegistry([FilesystemEvidenceProvider()])

        mission = _mission(
            tasks=[MissionTask(position=0, title="eslatma yoz", tool="note.write", agent="agent")]
        )
        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(auto_approve_write=True, auto_approve_medium=True),
            llm_provider=provider,
            evidence_registry=evidence_registry,
            task_timeout_s=5,
        )

        result = await executor.run(mission)

        assert result.all_done is True
        assert result.tasks[0].status == StepStatus.DONE
        assert result.tasks[0].verification_status == "verified"
        # HAQIQIY DALIL: fayl chindan ham diskda mavjud.
        written = await asyncio.to_thread(lambda: list(tmp_path.glob("*.md")))
        assert len(written) == 1
        content_on_disk = await asyncio.to_thread(written[0].read_text, encoding="utf-8")
        assert content_on_disk.strip().endswith("salom")

    async def test_note_write_evidence_directly_not_found(self, tmp_path: Path) -> None:
        """Provider mustaqil ishlaydi: kutilgan fayl haqiqatda yo'q bo'lsa
        — NOT_FOUND (soxta VERIFIED emas)."""
        provider = FilesystemEvidenceProvider()
        missing = tmp_path / "yoq.md"
        evidence = await provider.observe(
            tool_name="note.write", tool_output={"path": str(missing), "size_bytes": 10}
        )
        assert evidence.state == EvidenceState.NOT_FOUND
        assert evidence.authoritative is True


# ── C. GitHub — GitHubReadTool orqali (spec §3, §18.C) ────────────────


class TestGitHubEvidence:
    async def test_create_issue_verified_via_real_read_tool(self) -> None:
        """Stub rejim (token=None) — tarmoqqa chiqmaydi, LEKIN
        `GitHubReadTool`/`GitHubWriteTool`ning HAQIQIY, production kod
        yo'li ishlaydi (repo'ning mavjud stub-rejim konvensiyasi,
        `test_github_real_api.py` bilan bir xil)."""
        read_tool = GitHubReadTool(token=None)
        write_tool = GitHubWriteTool(token=None)
        provider = GitHubEvidenceProvider(read_tool)

        write_result = await write_tool.execute(
            {"action": "create_issue", "repo": "acme/demo", "title": "bug"}
        )
        assert write_result.success

        evidence = await provider.observe(tool_name="github.write", tool_output=write_result.output)

        # Stub rejimda `get_issue` HAR DOIM so'ralgan raqamni qaytaradi
        # (`_stub_get_issue`) — shu sabab mos keladi va FOUND bo'ladi.
        assert evidence.state == EvidenceState.FOUND
        assert evidence.authoritative is True

    async def test_add_comment_has_no_independent_read_action(self) -> None:
        """AUDIT TOPILMASI: `GitHubReadTool` bitta-comment GET amalini
        qo'llab-quvvatlamaydi — shu sabab `add_comment` uchun mustaqil
        tekshiruv UNKNOWN (soxta VERIFIED emas, HALOL "bila olmadik")."""
        read_tool = GitHubReadTool(token=None)
        provider = GitHubEvidenceProvider(read_tool)
        evidence = await provider.observe(
            tool_name="github.write",
            tool_output={"action": "add_comment", "repo": "acme/demo", "number": 1},
        )
        assert evidence.state == EvidenceState.UNKNOWN
        assert evidence.authoritative is False


# ── D. Telegram — message_id-asoslangan dalil (spec §4, §18.D) ───────


class TestTelegramEvidence:
    async def test_stub_send_has_no_message_id_so_not_found(self) -> None:
        """Stub rejimda `posted=False, message_id=0` — dalil YO'Q, shuning
        uchun NOT_FOUND (spec: agar API xabarni ishonchli tekshira
        olmasa — hech qachon soxta VERIFIED emas)."""
        provider = TelegramEvidenceProvider()
        evidence = await provider.observe(
            tool_name="telegram.channel_post",
            tool_output={"chat_id": "-100", "message_id": 0, "posted": False},
        )
        assert evidence.state == EvidenceState.NOT_FOUND

    async def test_real_message_id_is_found_but_not_persistently_confirmed(self) -> None:
        """HAQIQIY (simulyatsiya qilingan Telegram serveridan qaytgan)
        `message_id` — FOUND, lekin `confidence` past (Bot API keyinroq
        xabarni GET qila olmaydi — spec §4 cheklovi, ochiq e'lon
        qilingan)."""
        provider = TelegramEvidenceProvider()
        evidence = await provider.observe(
            tool_name="telegram.channel_post",
            tool_output={"chat_id": "-100", "message_id": 555, "posted": True},
        )
        assert evidence.state == EvidenceState.FOUND
        assert evidence.confidence < 0.95  # fayl-tizimi darajasidagi qat'iyatdan PAST


# ── E. HTTP/API — Instagram WRITE→GET namunasi (spec §5, §18.E) ──────


class _FakeRecentMediaTool:
    """`instagram.recent_media`ning minimal, sinov uchun ishlatiladigan
    o'rnini bosuvchisi — HAQIQIY tool bilan BIR XIL kontrakt
    (`.execute(params) -> ToolResult`), lekin tarmoqqa chiqmaydi."""

    def __init__(self, media_ids: list[str]) -> None:
        self._media_ids = media_ids

    async def execute(self, params: dict[str, Any]) -> Any:
        from zet.domain.tool import ToolResult

        del params
        return ToolResult(
            tool_name="instagram.recent_media",
            success=True,
            output={"media": [{"id": mid} for mid in self._media_ids], "count": len(self._media_ids)},
        )


class TestInstagramEvidenceWriteThenGet:
    async def test_published_post_found_in_recent_media(self) -> None:
        provider = InstagramEvidenceProvider(_FakeRecentMediaTool(["abc123", "def456"]))
        evidence = await provider.observe(
            tool_name="instagram.publish_photo",
            tool_output={"media_id": "abc123", "posted": True},
        )
        assert evidence.state == EvidenceState.FOUND
        assert evidence.authoritative is True

    async def test_missing_post_not_found_in_recent_media(self) -> None:
        provider = InstagramEvidenceProvider(_FakeRecentMediaTool(["other111"]))
        evidence = await provider.observe(
            tool_name="instagram.publish_photo",
            tool_output={"media_id": "abc123", "posted": True},
        )
        assert evidence.state == EvidenceState.NOT_FOUND


# ── Camera — metadata tekshiruvi (spec §6) ────────────────────────────


class TestCameraEvidence:
    async def test_valid_snapshot_metadata_found(self) -> None:
        provider = CameraEvidenceProvider()
        evidence = await provider.observe(
            tool_name="camera.snapshot",
            tool_output={"has_image": True, "image_b64": "aGVsbG8=", "width": 640, "height": 480},
        )
        assert evidence.state == EvidenceState.FOUND

    async def test_missing_image_not_found(self) -> None:
        provider = CameraEvidenceProvider()
        evidence = await provider.observe(
            tool_name="camera.snapshot", tool_output={"has_image": False}
        )
        assert evidence.state == EvidenceState.NOT_FOUND


# ── F/G. Tool substitution — mos/mos EMAS (spec §10-12, §18.F/G) ─────


class TestToolSubstitutionCompatible:
    async def test_failed_tool_substituted_with_compatible_alternative(self) -> None:
        """F: `x_v1` (TOOL-sinf xato) → bir xil `capability_tag`/
        `permission_level`/`risk_level`ga ega `x_v2` bilan almashtiriladi
        va muvaffaqiyatli yakunlanadi.

        MUHIM (JB-14/15 audit topilmasi — `AgentRuntime.run()`ning O'Z
        ReAct sikli, `test_task_graph_verification_and_recovery.py`da
        aniqlangan): bitta tool xatosi o'zi tashqi (TaskGraph darajasidagi)
        `AgentRunResult.success=False` HOSIL QILMAYDI — suhbat kontekstiga
        qaytariladi va LLM davom etadi. Shu sabab `max_tool_calls=1`
        ishlatiladi: birinchi (muvaffaqiyatsiz) tool chaqiruvi sarflanadi,
        ikkinchi qadamda LLM яna SHU toolni so'raganda `AgentMaxToolCallsError`
        chiqadi — bu ANIQ, tashqariga `AgentRunResult(success=False)`
        sifatida chiqadigan chegara."""
        registry = AgentRegistry()
        registry.register(
            _agent_spec("agent", tools=["x_v1", "x_v2"], max_tool_calls=1),
            status=AgentStatus.ACTIVE,
        )
        tools = ToolRegistry()
        failing = _StubTool(
            "x_v1", outcomes=[ToolError("doim xato")], capability_tag="do_x", idempotent=True
        )
        working = _StubTool("x_v2", outcomes=["ok"], capability_tag="do_x")
        tools.register(failing)
        tools.register(working)

        provider = FakeProvider(
            scripted=[
                fake_response(tool_uses=(_tool_use("x_v1"),)),  # 1-qadam: x_v1 xato
                fake_response(tool_uses=(_tool_use("x_v1"),)),  # 2-qadam: max_tool_calls
                fake_response(tool_uses=(_tool_use("x_v2"),)),  # muqobil tool: OK
                fake_response(text="Bajarildi."),  # yakuniy javob
            ]
        )
        mission = _mission(tasks=[MissionTask(position=0, title="x", tool="x_v1", agent="agent")])
        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(auto_approve_write=True, auto_approve_medium=True),
            llm_provider=provider,
            max_retries=0,
            tool_resolver=ToolSubstitutionResolver(tools),
            task_timeout_s=5,
        )

        result = await executor.run(mission)

        assert result.all_done is True
        assert result.tasks[0].status == StepStatus.DONE
        assert result.tasks[0].tool == "x_v2", "Muqobil toolga o'tish kutilgan edi"
        assert len(working.calls) == 1


class TestToolSubstitutionIncompatible:
    async def test_higher_risk_alternative_is_never_selected(self) -> None:
        """G: `y_safe` (LOW risk) muvaffaqiyatsiz bo'lsa, `y_risky`
        (bir xil `capability_tag`, LEKIN HIGH risk) hech qachon
        tanlanmasligi kerak — resolver `None` qaytaradi, task oddiy
        FAILED bo'ladi (muqobil AGENT ham yo'q bu testda)."""
        registry = AgentRegistry()
        registry.register(
            _agent_spec("agent", tools=["y_safe"], max_tool_calls=1), status=AgentStatus.ACTIVE
        )
        tools = ToolRegistry()
        failing = _StubTool(
            "y_safe",
            outcomes=[ToolError("xato")],
            capability_tag="do_y",
            risk_level=RiskLevel.LOW,
        )
        risky = _StubTool(
            "y_risky", outcomes=["ok"], capability_tag="do_y", risk_level=RiskLevel.HIGH
        )
        tools.register(failing)
        tools.register(risky)

        provider = FakeProvider(
            scripted=[
                fake_response(tool_uses=(_tool_use("y_safe"),)),  # 1-qadam: xato
                fake_response(tool_uses=(_tool_use("y_safe"),)),  # 2-qadam: max_tool_calls
            ]
        )
        mission = _mission(tasks=[MissionTask(position=0, title="y", tool="y_safe", agent="agent")])
        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(auto_approve_write=True, auto_approve_medium=True),
            llm_provider=provider,
            max_retries=0,
            tool_resolver=ToolSubstitutionResolver(tools),
            task_timeout_s=5,
        )

        result = await executor.run(mission)

        assert result.tasks[0].status == StepStatus.FAILED
        assert result.tasks[0].tool == "y_safe", "Xavfli muqobilga O'TMASLIGI kerak edi"
        assert risky.calls == []


# ── H. Muqobil tool topilmasa — muqobil AGENT hamon ishlaydi ──────────


class TestAlternateAgentStillWorksAlongsideResolver:
    async def test_no_matching_tool_falls_back_to_alternate_agent(self) -> None:
        """H: `tool_resolver` BERILGAN, lekin mos muqobil tool YO'Q
        (`capability_tag=None`) — JB-14'ning muqobil AGENT yo'li hamon
        ishlashi kerak (regressiya yo'q)."""
        from zet.core.agent_selector import AgentSelector

        registry = AgentRegistry()
        registry.register(_agent_spec("a_alt", tools=["z"]), status=AgentStatus.ACTIVE)
        registry.register(
            _agent_spec("b_main", tools=["z"], max_tool_calls=1),
            status=AgentStatus.ACTIVE,
        )
        tools = ToolRegistry()
        stub = _StubTool("z", outcomes=[ToolError("xato"), "ok"], capability_tag=None)
        tools.register(stub)

        provider = FakeProvider(
            scripted=[
                fake_response(tool_uses=(_tool_use("z"),)),  # b_main 1-qadam: xato
                fake_response(tool_uses=(_tool_use("z"),)),  # b_main 2-qadam: max_tool_calls
                fake_response(tool_uses=(_tool_use("z"),)),  # a_alt: OK
                fake_response(text="Bajarildi."),  # a_alt yakuniy javob
            ]
        )
        mission = _mission(tasks=[MissionTask(position=0, title="z", tool="z", agent="b_main")])
        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(auto_approve_write=True, auto_approve_medium=True),
            llm_provider=provider,
            max_retries=0,
            tool_resolver=ToolSubstitutionResolver(tools),  # mavjud, lekin muqobil TOPMAYDI
            agent_selector=AgentSelector(registry),
            task_timeout_s=5,
        )

        result = await executor.run(mission)

        assert result.all_done is True
        assert result.tasks[0].agent == "a_alt"
        assert result.tasks[0].tool == "z"  # tool o'zgarmadi — faqat agent


# ── I. Tashqi noaniqlik — ko'r-ko'rona qayta urinish YO'Q ─────────────


class _UnknownEvidenceProvider:
    """Har doim UNKNOWN qaytaradi — masalan tarmoq/tashqi so'rov
    muvaffaqiyatsiz bo'lgan holatni simulyatsiya qiladi."""

    def supports(self, tool_name: str) -> bool:
        return tool_name == "w"

    async def observe(self, *, tool_name: str, tool_output: Any) -> Any:
        from datetime import UTC, datetime

        from zet.core.evidence import Evidence

        del tool_name, tool_output
        return Evidence(
            source="test",
            state=EvidenceState.UNKNOWN,
            observed_state={},
            timestamp=datetime.now(UTC),
            authoritative=False,
            confidence=0.0,
            reason="tashqi so'rov vaqti tugadi (simulyatsiya)",
        )


class TestExternalUncertaintyBlocksBlindRetry:
    async def test_unknown_evidence_does_not_reexecute_non_idempotent_tool(self) -> None:
        registry = AgentRegistry()
        registry.register(_agent_spec("agent", tools=["w"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        stub = _StubTool("w", outcomes=["ok"], idempotent=False)
        tools.register(stub)

        evidence_registry = EvidenceProviderRegistry([_UnknownEvidenceProvider()])
        provider = FakeProvider(scripted=[fake_response(tool_uses=(_tool_use("w"),))])
        mission = _mission(tasks=[MissionTask(position=0, title="w", tool="w", agent="agent")])
        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(auto_approve_write=True, auto_approve_medium=True),
            llm_provider=provider,
            evidence_registry=evidence_registry,
            task_timeout_s=5,
        )

        result = await executor.run(mission)
        assert result.tasks[0].verification_status == "verification_uncertain"
        assert len(stub.calls) == 1

        provider2 = FakeProvider(scripted=[])
        executor2 = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(auto_approve_write=True, auto_approve_medium=True),
            llm_provider=provider2,
            evidence_registry=evidence_registry,
            task_timeout_s=5,
        )
        await executor2.run(mission)
        assert len(stub.calls) == 1, "UNKNOWN dalil + idempotent-emas tool QAYTA chaqirilmasligi kerak"


# ── J. Killswitch — muqobil tool SINALMAYDI ham ───────────────────────


class TestKillswitchBlocksToolSubstitution:
    async def test_engaged_killswitch_prevents_alternative_selection(self) -> None:
        registry = AgentRegistry()
        registry.register(_agent_spec("agent", tools=["k1", "k2"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        failing = _StubTool("k1", outcomes=[ToolError("xato")], capability_tag="do_k")
        alt = _StubTool("k2", outcomes=["ok"], capability_tag="do_k")
        tools.register(failing)
        tools.register(alt)

        killswitch = KillSwitchState()
        killswitch.engage(reason="test to'xtash")

        provider = FakeProvider(scripted=[fake_response(tool_uses=(_tool_use("k1"),))] * 3)
        mission = _mission(tasks=[MissionTask(position=0, title="k", tool="k1", agent="agent")])
        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(auto_approve_write=True, auto_approve_medium=True),
            llm_provider=provider,
            max_retries=0,
            tool_resolver=ToolSubstitutionResolver(tools),
            killswitch=killswitch,
            task_timeout_s=5,
        )

        result = await executor.run(mission)

        assert result.tasks[0].status == StepStatus.FAILED
        assert result.tasks[0].tool == "k1", "Killswitch yoqilganda muqobil SINALMASLIGI kerak"
        assert alt.calls == []


# ── K. Ruxsat — resolver ruxsatni OSHIRMAYDI ──────────────────────────


class TestResolverPermissionSafety:
    def test_insufficient_caller_permission_blocks_alternative(self) -> None:
        tools = ToolRegistry()
        failing = _StubTool(
            "p1", capability_tag="do_p", permission_level=PermissionLevel.WRITE
        )
        candidate = _StubTool(
            "p2", capability_tag="do_p", permission_level=PermissionLevel.WRITE
        )
        tools.register(failing)
        tools.register(candidate)
        resolver = ToolSubstitutionResolver(tools)

        # Chaqiruvchi ruxsati WRITE'dan PAST (READ) — hech qachon berilmaydi.
        alt = resolver.find_alternative("p1", caller_permission=PermissionLevel.READ)
        assert alt is None

        # Yetarli ruxsat bilan — topiladi.
        alt2 = resolver.find_alternative("p1", caller_permission=PermissionLevel.WRITE)
        assert alt2 is not None
        assert alt2.name == "p2"

    def test_no_capability_tag_never_matches(self) -> None:
        tools = ToolRegistry()
        tools.register(_StubTool("q1", capability_tag=None))
        tools.register(_StubTool("q2", capability_tag=None))
        resolver = ToolSubstitutionResolver(tools)
        assert resolver.find_alternative("q1", caller_permission=PermissionLevel.ADMIN) is None


# ── L. Approval — yuqori xavfli muqobil AVTOMATIK bypass qilinmaydi ──


class TestApprovalGateNotBypassedBySubstitution:
    async def test_high_risk_alternative_fails_closed_without_approval(self) -> None:
        """L: `r1`/`r2` ikkalasi ham HIGH risk (resolver shu sabab `r2`ni
        tanlaydi — xavf oshmadi). LEKIN `PermissionPolicy` HIGH riskni
        HAR DOIM tasdiq talab qiladi deb belgilaydi — `AgentRuntime`
        (JB-14'dan beri o'zgarmagan, avtonom oqim tasdiqni qo'llab-
        quvvatlamaydi) muqobilni FAIL-CLOSED rad etadi. Natija: hech
        qanday approval BYPASS qilinmaydi — task oddiy FAILED bilan
        tugaydi ("kutish" emas, xavfsiz rad etish, JB-14 bilan bir xil
        ochiq e'lon qilingan tanlov)."""
        registry = AgentRegistry()
        registry.register(
            _agent_spec("agent", tools=["r1", "r2"], max_tool_calls=1), status=AgentStatus.ACTIVE
        )
        tools = ToolRegistry()
        failing = _StubTool(
            "r1", outcomes=[ToolError("xato")], capability_tag="do_r", risk_level=RiskLevel.HIGH
        )
        risky_alt = _StubTool(
            "r2", outcomes=["ok"], capability_tag="do_r", risk_level=RiskLevel.HIGH
        )
        tools.register(failing)
        tools.register(risky_alt)

        provider = FakeProvider(
            scripted=[
                fake_response(tool_uses=(_tool_use("r1"),)),  # 1-qadam: approval rad etadi
                fake_response(tool_uses=(_tool_use("r1"),)),  # 2-qadam: max_tool_calls
                fake_response(tool_uses=(_tool_use("r2"),)),  # muqobil: approval YANA rad etadi
                fake_response(tool_uses=(_tool_use("r2"),)),  # 2-qadam: max_tool_calls
            ]
        )
        mission = _mission(tasks=[MissionTask(position=0, title="r", tool="r1", agent="agent")])
        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            # auto_approve YO'Q — HIGH risk HAR DOIM tasdiq talab qiladi
            # (`PermissionPolicy` default siyosati).
            permission_policy=PermissionPolicy(),
            llm_provider=provider,
            max_retries=0,
            tool_resolver=ToolSubstitutionResolver(tools),
            task_timeout_s=5,
        )

        result = await executor.run(mission)

        assert result.tasks[0].status == StepStatus.FAILED
        # Muqobil TANLANDI (tool_substitution.resolved), lekin HAQIQATDA
        # muvaffaqiyatli BAJARILMADI — approval gate uni to'xtatdi.
        assert risky_alt.calls == [], "Approval gate chetlab o'tilmasligi kerak edi"


# ── M. To'liq tsikl — evidence + tool substitution birga ─────────────


class TestFullLoopWithEvidenceAndSubstitution:
    async def test_full_loop_tool_fails_substitutes_then_evidence_verifies(
        self, tmp_path: Path
    ) -> None:
        """INPUT → TaskGraph → Tool(muvaffaqiyatsiz) → ToolSubstitutionResolver
        → Tool(muqobil) → EvidenceProvider(haqiqiy fs) → VERIFIED →
        Completion."""
        registry = AgentRegistry()
        registry.register(
            _agent_spec(
                "agent", tools=["note.write.broken", "note.write"], max_tool_calls=1
            ),
            status=AgentStatus.ACTIVE,
        )
        broken = _StubTool(
            "note.write.broken",
            outcomes=[ToolError("xizmat ishlamayapti")],
            capability_tag="fs.write",
            # `note.write`ning HAQIQIY xavf darajasi (`risk_for()` markaziy
            # jadvalidan) — MEDIUM. Resolver past xavfni yuqori xavf bilan
            # almashtirishga ruxsat BERMAYDI, shuning uchun mos kelishi
            # uchun bu yerda ANIQ moslashtiriladi.
            risk_level=RiskLevel.MEDIUM,
        )

        # `capability_tag`ni haqiqiy tool'ga runtime'da qo'shib bo'lmaydi
        # (property, subclass emas) — shu sabab shu testda MUVOFIQ
        # subclass orqali belgilaymiz (haqiqiy `NoteWriteTool._execute()`
        # o'zgarmagan — faqat metadata override).
        class _TaggedNoteWrite(NoteWriteTool):
            @property
            def capability_tag(self) -> str | None:
                return "fs.write"

        tools = ToolRegistry()
        tools.register(broken)
        tools.register(_TaggedNoteWrite(notes_dir=tmp_path))

        provider = FakeProvider(
            scripted=[
                fake_response(tool_uses=(_tool_use("note.write.broken"),)),  # 1-qadam: xato
                fake_response(tool_uses=(_tool_use("note.write.broken"),)),  # 2-qadam: max_tool_calls
                fake_response(
                    tool_uses=(
                        _tool_use("note.write", {"title": "yakuniy", "content": "to'liq tsikl"}),
                    )
                ),  # muqobil tool: OK
                fake_response(text="Bajarildi."),  # yakuniy javob
            ]
        )
        evidence_registry = EvidenceProviderRegistry([FilesystemEvidenceProvider()])
        mission = _mission(
            tasks=[
                MissionTask(position=0, title="yoz", tool="note.write.broken", agent="agent")
            ]
        )
        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(auto_approve_write=True, auto_approve_medium=True),
            llm_provider=provider,
            max_retries=0,
            tool_resolver=ToolSubstitutionResolver(tools),
            evidence_registry=evidence_registry,
            task_timeout_s=5,
        )

        result = await executor.run(mission)

        assert result.all_done is True
        assert result.tasks[0].tool == "note.write"
        assert result.tasks[0].verification_status == "verified"
        written = await asyncio.to_thread(lambda: list(tmp_path.glob("*.md")))
        assert len(written) == 1


# ── R/S. Ko'p bosqichli GitHub audit missiyasi (spec Phase 12 R/S) ───


class TestMultiStepGitHubAuditMission:
    async def test_inspect_then_write_then_externally_verify(self) -> None:
        """1-vazifa: repo'ni TEKSHIRISH (`github.read`, faqat o'qish —
        evidence NOT_REQUIRED, tashqi yon-samar yo'q). 2-vazifa (1-ga
        bog'liq): SO'ROV QILINGAN amalni bajarish (`github.write` —
        issue yaratish) VA HAQIQIY GitHub holatini (`GitHubEvidenceProvider`
        orqali, stub rejimda — tarmoqsiz, lekin HAQIQIY kod yo'li) tasdiqlash.
        Ikkalasi ham BITTA TaskGraphExecutor.run() orqali, real DAG
        bog'liqligi bilan."""
        registry = AgentRegistry()
        registry.register(
            _agent_spec("auditor", tools=["github.read", "github.write"]),
            status=AgentStatus.ACTIVE,
        )
        tools = ToolRegistry()
        read_tool = GitHubReadTool(token=None)

        # `github.write`ning HAQIQIY xavf darajasi (`risk_for()`) — HIGH,
        # V-32 bo'yicha HECH QANDAY siyosat bilan chetlab o'tilmaydi
        # (approval gate ATAYLAB, alohida testda — `TestApprovalGateNot
        # BypassedBySubstitution` — tekshiriladi). Bu testning maqsadi —
        # EVIDENCE tekshiruvi (approval EMAS), shu sabab shu yerda LOW'ga
        # tushiriladi (haqiqiy `_execute()` mantiq O'ZGARMAGAN, faqat
        # metadata).
        class _LowRiskGitHubWriteTool(GitHubWriteTool):
            @property
            def risk_level(self) -> RiskLevel:
                return RiskLevel.LOW

        write_tool = _LowRiskGitHubWriteTool(token=None)
        tools.register(read_tool)
        tools.register(write_tool)

        provider = FakeProvider(
            scripted=[
                # 1-vazifa: repo tekshiruvi (READ — tashqi yon-samar yo'q).
                fake_response(
                    tool_uses=(
                        _tool_use("github.read", {"action": "list_issues", "repo": "acme/demo"}),
                    )
                ),
                fake_response(text="Repo tekshirildi — 2 ta ochiq issue bor."),
                # 2-vazifa: so'ralgan amal (WRITE) + yakuniy javob.
                fake_response(
                    tool_uses=(
                        _tool_use(
                            "github.write",
                            {"action": "create_issue", "repo": "acme/demo", "title": "audit topilmasi"},
                        ),
                    )
                ),
                fake_response(text="Issue yaratildi."),
            ]
        )
        evidence_registry = EvidenceProviderRegistry([GitHubEvidenceProvider(read_tool)])
        mission = _mission(
            tasks=[
                MissionTask(
                    position=0, title="repo tekshir", tool="github.read", agent="auditor"
                ),
                MissionTask(
                    position=1,
                    title="issue yarat",
                    tool="github.write",
                    agent="auditor",
                    depends_on=[0],
                ),
            ]
        )
        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(auto_approve_write=True, auto_approve_medium=True),
            llm_provider=provider,
            evidence_registry=evidence_registry,
            task_timeout_s=5,
        )

        result = await executor.run(mission)

        assert result.all_done is True
        # 1-vazifa (READ) — evidence provider'i yo'q (faqat github.write
        # uchun ro'yxatdan o'tgan) → eski (Verifier-yo'q) yo'l, DONE.
        assert result.tasks[0].status == StepStatus.DONE
        # 2-vazifa (WRITE) — HAQIQIY GitHub (stub) holati bilan tasdiqlangan.
        assert result.tasks[1].status == StepStatus.DONE
        assert result.tasks[1].verification_status == "verified"
