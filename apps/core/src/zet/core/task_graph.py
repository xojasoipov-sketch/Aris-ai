"""Task Graph Executor — mission ichidagi ko'p taskni HAQIQIY DAG bo'yicha bajarish (JB-5).

NEGA bu qatlam kerak. `MissionEngine.execute()` ilgari butun missionni
BITTA `Command` sifatida Orchestrator.start()'ga uzatardi — `mission.tasks`
(`_bundle_to_tasks()` qurgan) faqat KO'RGAZMA uchun saqlanardi, hech qanday
kod ularni alohida bajarmasdi, alohida agentga bog'lamasdi, alohida qayta
urinmasdi. Ya'ni "Task Graph" nomi bor edi, lekin mission bir butun buyruq
sifatida ijro etilardi (ko'p tool/ko'p agentli maqsadlar uchun bitta LLM
tool-loop'ga qoldirilardi).

`TaskGraphExecutor` bu bo'shliqni to'ldiradi: `mission.tasks`ni Kahn
algoritmi bilan parallel-bajariladigan bosqichlarga guruhlaydi (`dag.py`
bilan bir xil naqsh, lekin `PlanStep` emas `MissionTask` ustida), har
bosqichdagi taskni `automation.executor.run_agent_command()` orqali —
FAQAT o'sha taskka tayinlangan agent va FAQAT o'sha taskning tooli bilan
— ishga tushiradi, muvaffaqiyatsizlikni retry qiladi, bog'liq task
muvaffaqiyatsiz bo'lsa pastki oqimni SKIPPED (bloklangan) deb belgilaydi
va yakunda mission-darajali sintez matni tuzadi.

MUHIM — HALOL DOIRA (JB-5 spetsifikatsiyasi talab qilgan ochiq kamchilik):
    Bu — LLM erkin ravishda o'ylab topgan ixtiyoriy task dekompozitsiyasi
    EMAS. Har bir `MissionTask` — `CapabilityRegistryComposer.compose()`
    tanlagan BITTA tool chaqiruvi; bog'liqliklar esa capability-darajasidagi
    HAQIQIY DAG'dan (`_tool_dependencies_from_capabilities`, JB-5)
    deterministik hosil qilinadi. "8 ta ixtiyoriy task, LLM tanlagan"
    ko'rinishidagi erkin dekompozitsiya BU YERDA YO'Q — bu ataylab
    tanlangan, kichikroq va tekshirib bo'ladigan qamrov.

    Task-ichi (mid-graph) approval-so'rab-kutish/resume ham QURILMAGAN —
    mission-darajasidagi oldindan tekshiruv (`MissionEngine.plan()`dagi
    `risk.requires_approval`) butun bundle uchun approval oladi; alohida
    task ijrosi paytida approval kerak bo'lib qolsa (masalan LLM kutilmagan
    HIGH-risk tool so'rasa) — `AgentRuntime` buni FAIL-CLOSED rad etadi
    (V-32: avtonom ijro tasdiqni chetlab o'ta olmaydi), task esa xato bilan
    FAILED bo'ladi. Bu — "avtomatik bypass"dan farqli, xavfsiz tanlov.

Bog'liq qarorlar:
    A-01 — davomli holat mashinasi (MissionTask.status DB'da saqlanadi)
    A-07 — avtonomiya tormozlari (retry/timeout chegaralari)
    V-31/V-32 — tool ruxsati va majburiy tasdiq (AgentRuntime orqali)
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

from zet.automation.executor import AgentUnavailableError, run_agent_command
from zet.db.base import utcnow
from zet.domain.enums import StepStatus

if TYPE_CHECKING:
    from zet.agents.registry import AgentRegistry
    from zet.core.mission import Mission, MissionTask
    from zet.llm.base import LLMProvider
    from zet.security.permissions import PermissionPolicy
    from zet.tools.registry import ToolRegistry

log = structlog.get_logger(__name__)


class TaskGraphError(Exception):
    """Task Graph darajasidagi umumiy xato."""


class TaskGraphCycleError(TaskGraphError):
    """`MissionTask.depends_on` grafida sikl aniqlandi."""


@dataclass(frozen=True, slots=True)
class CapabilityGap:
    """Task uchun mos ACTIVE agent topilmadi yoki ijro paytida yo'qoldi.

    NEGA alohida tip: JB-5 spetsifikatsiyasi aniq talab qiladi — "mos agent
    topilmasa jim boshqa agent bilan bajarmang, Capability Gap qaytaring".
    Bu — kelajakdagi Agent Factory (JB-6+) uchun TOZA INTERFEYS; hozircha
    Agent Factory'ning o'zi QURILMAGAN — gap faqat aniqlanadi va
    `TaskGraphResult.capability_gaps`ga yoziladi, hech narsa "o'zi tuzatib
    qo'ymaydi" (fake avtonomiya emas).
    """

    tool: str
    reason: str


@dataclass
class TaskGraphResult:
    """`TaskGraphExecutor.run()` natijasi."""

    tasks: list[MissionTask]
    all_done: bool
    any_failed: bool
    any_blocked: bool
    synthesized_text: str
    capability_gaps: list[CapabilityGap] = field(default_factory=list)


_SKIP_STATUSES = (StepStatus.DONE, StepStatus.FAILED, StepStatus.SKIPPED)
"""Batch ichida ishga tushirilmaydigan holatlar (himoya — normal oqimda
`run()` boshida reset qilingani uchun faqat DONE qoladi, qolganlari
himoya sifatida)."""


class TaskGraphExecutor:
    """`Mission.tasks`ni HAQIQIY DAG bo'yicha, per-task agent-scoped bajaradi.

    Har bosqich (Kahn batch) ichidagi tasklar `asyncio.gather` bilan
    PARALLEL ishga tushiriladi (project'ning mavjud `plan_to_dag`/Executor
    naqshi bilan bir xil, yangi infratuzilma qo'shilmagan). Bosqichlar
    o'zaro KETMA-KET — keyingi bosqich faqat oldingisi tugagach boshlanadi
    (dependency kafolati).
    """

    def __init__(
        self,
        *,
        agent_registry: AgentRegistry,
        tool_registry: ToolRegistry,
        permission_policy: PermissionPolicy,
        llm_provider: LLMProvider | None = None,
        max_retries: int = 1,
        task_timeout_s: int | None = 120,
    ) -> None:
        self._agents = agent_registry
        self._tools = tool_registry
        self._permissions = permission_policy
        self._llm_provider = llm_provider
        self._max_retries = max_retries
        self._task_timeout_s = task_timeout_s

    async def run(self, mission: Mission) -> TaskGraphResult:
        """`mission.tasks`ni tugaguncha (yoki bloklanguncha) bajaradi.

        Resume/qayta urinish siyosati (idempotency): FAQAT `DONE` tasklar
        HECH QACHON qayta ishga tushirilmaydi — jarayon qayta boshlangan
        (process restart, `RUNNING`da qotib qolgan task) yoki mission-level
        recovery (`MissionEngine.recover()` EXECUTING'ga qaytarganda) shu
        `run()` QAYTA chaqiriladi. Ikkala holatda ham `FAILED`/`SKIPPED`/
        `RUNNING` tasklar `PENDING`ga qaytariladi va QAYTA sinaladi —
        aks holda bitta task muvaffaqiyatsiz bo'lgach, mission-level
        recovery hech qachon uni tuzata olmasdi (abadiy bloklangan bo'lardi).
        """
        tasks = list(mission.tasks)
        if not tasks:
            return TaskGraphResult(
                tasks=tasks,
                all_done=True,
                any_failed=False,
                any_blocked=False,
                synthesized_text="",
            )

        for task in tasks:
            if task.status != StepStatus.DONE:
                task.status = StepStatus.PENDING

        try:
            batches = _tasks_to_batches(tasks)
        except TaskGraphCycleError as exc:
            for task in tasks:
                if task.status not in _SKIP_STATUSES:
                    task.status = StepStatus.FAILED
                    task.error = str(exc)
            log.warning("task_graph.cycle_detected", mission_id=str(mission.id), error=str(exc))
            return TaskGraphResult(
                tasks=tasks,
                all_done=False,
                any_failed=True,
                any_blocked=False,
                synthesized_text=f"Task graph xato: {exc}",
            )

        by_position = {t.position: t for t in tasks}
        capability_gaps: list[CapabilityGap] = []
        any_failed = False

        for batch in batches:
            runnable = [t for t in batch if t.status not in _SKIP_STATUSES]
            if not runnable:
                continue

            to_run: list[MissionTask] = []
            for task in runnable:
                blocker = _blocking_failed_dependency(task, by_position)
                if blocker is not None:
                    task.status = StepStatus.SKIPPED
                    task.error = f"bloklandi: bog'liq task #{blocker} muvaffaqiyatsiz tugadi"
                    any_failed = True
                    continue
                to_run.append(task)

            if not to_run:
                continue

            gaps = await asyncio.gather(*(self._run_task(mission, t) for t in to_run))
            for task, gap in zip(to_run, gaps, strict=True):
                if gap is not None:
                    capability_gaps.append(gap)
                if task.status == StepStatus.FAILED:
                    any_failed = True

        any_blocked = any(t.status == StepStatus.SKIPPED for t in tasks)
        all_done = all(t.status == StepStatus.DONE for t in tasks)
        synthesized_text = _synthesize(mission, tasks)

        log.info(
            "task_graph.completed",
            mission_id=str(mission.id),
            tasks=len(tasks),
            all_done=all_done,
            any_failed=any_failed,
            any_blocked=any_blocked,
            capability_gaps=len(capability_gaps),
        )

        return TaskGraphResult(
            tasks=tasks,
            all_done=all_done,
            any_failed=any_failed,
            any_blocked=any_blocked,
            synthesized_text=synthesized_text,
            capability_gaps=capability_gaps,
        )

    async def _run_task(self, mission: Mission, task: MissionTask) -> CapabilityGap | None:
        """Bitta taskni — agent-scoped, tool-scoped, retry/timeout bilan bajaradi.

        Tool chegarasi (V-31 kengaytmasi, "task o'z tooli bilan cheklangan"):
        LLM boshqa tool nomini so'rasa ham, agentga uzatilgan registry
        FAQAT `task.tool`ni o'z ichiga oladi — `ToolRegistry.subset()`
        (JB-4) bilan bir xil naqsh, endi mission darajasidan TASK
        darajasiga tushirilgan.
        """
        if task.agent is None:
            no_agent_gap = CapabilityGap(
                tool=task.tool or task.title,
                reason="mos ACTIVE agent topilmadi (compose bosqichida tanlanmagan)",
            )
            task.status = StepStatus.FAILED
            task.error = (
                f"Capability gap: '{no_agent_gap.tool}' uchun agent topilmadi — "
                "begona agent bilan avtomatik bajarilmadi (Agent Factory hali qurilmagan)."
            )
            log.info(
                "task_graph.capability_gap",
                mission_id=str(mission.id),
                task=task.title,
                reason=no_agent_gap.reason,
            )
            return no_agent_gap

        scoped_tools = self._tools.subset([task.tool]) if task.tool else self._tools
        command = _task_command_text(mission, task)

        attempt = 0
        last_error: str | None = None
        gap: CapabilityGap | None = None
        while True:
            task.status = StepStatus.RUNNING
            task.started_at = task.started_at or utcnow()
            try:
                result = await run_agent_command(
                    task.agent,
                    command,
                    agent_registry=self._agents,
                    tool_registry=scoped_tools,
                    permission_policy=self._permissions,
                    timeout_s=self._task_timeout_s,
                    provider=self._llm_provider,
                )
            except AgentUnavailableError as exc:
                # Reja tuzilgandan beri agent PAUSED/o'chirilgan bo'lishi
                # mumkin — bu ham Capability Gap (begona agentga
                # o'tkazilmaydi), oddiy retry emas.
                gap = CapabilityGap(tool=task.tool or task.title, reason=str(exc))
                last_error = str(exc)
                log.info(
                    "task_graph.agent_unavailable",
                    mission_id=str(mission.id),
                    task=task.title,
                    agent=task.agent,
                    error=last_error,
                )
                break
            except TimeoutError:
                last_error = f"vaqt tugadi ({self._task_timeout_s}s)"
            except Exception as exc:  # task darajasida yutiladi — mission davom etadi
                last_error = f"kutilmagan xato: {type(exc).__name__}: {exc}"
                log.warning(
                    "task_graph.task_error",
                    mission_id=str(mission.id),
                    task=task.title,
                    error=last_error,
                )
            else:
                if result.success:
                    task.status = StepStatus.DONE
                    task.result = (result.output or "")[:2000]
                    task.error = None
                    task.completed_at = utcnow()
                    return None
                last_error = result.error or "agent muvaffaqiyatsiz tugadi"

            attempt += 1
            if attempt > self._max_retries:
                break
            task.retries = attempt
            log.info(
                "task_graph.retry",
                mission_id=str(mission.id),
                task=task.title,
                attempt=attempt,
                error=last_error,
            )

        task.status = StepStatus.FAILED
        task.error = last_error or "nomalum xato"
        task.completed_at = utcnow()
        return gap


def _task_command_text(mission: Mission, task: MissionTask) -> str:
    """Task uchun agentga uzatiladigan buyruq matni.

    Missiya maqsadi + shu taskning aniq maqsadi (tool nomi) — agent FAQAT
    shu bitta toolga ega bo'lgani uchun (`scoped_tools`), model o'sha
    tooldan foydalanishga majbur bo'ladi.
    """
    lines = [f"MISSIYA MAQSADI: {mission.objective}"]
    if task.tool:
        lines.append(f"SHU VAZIFA: '{task.tool}' toolidan foydalanib quyidagini bajar: {task.title}")
    else:
        lines.append(f"SHU VAZIFA: {task.title}")
    return "\n".join(lines)


def _blocking_failed_dependency(
    task: MissionTask, by_position: dict[int, MissionTask]
) -> int | None:
    """`task.depends_on`dagi biror dependency FAILED/SKIPPED bo'lsa — o'sha pozitsiya.

    NEGA SKIPPED ham bloklaydi: bloklanish transitiv — A muvaffaqiyatsiz
    bo'lsa, A'ga bog'liq B SKIPPED bo'ladi, B'ga bog'liq C ham SKIPPED
    bo'lishi kerak (zanjir bo'ylab tarqaladi).
    """
    for dep_pos in task.depends_on:
        dep = by_position.get(dep_pos)
        if dep is not None and dep.status in (StepStatus.FAILED, StepStatus.SKIPPED):
            return dep_pos
    return None


def _tasks_to_batches(tasks: Sequence[MissionTask]) -> list[list[MissionTask]]:
    """`MissionTask.depends_on` DAG'ini Kahn bosqichlariga guruhlaydi.

    `core/dag.py::plan_to_dag` bilan bir xil algoritm (Kahn), lekin
    `PlanStep` o'rniga `MissionTask` ustida — alohida modul, chunki
    Mission Task Graph reja bosqichi (`Plan`) emas, Mission darajasida
    yashaydi va boshqa maydon to'plamiga ega.
    """
    if not tasks:
        return []

    by_pos = {t.position: t for t in tasks}
    in_degree = {t.position: len(t.depends_on) for t in tasks}
    dependents: dict[int, list[int]] = {t.position: [] for t in tasks}
    for task in tasks:
        for dep in task.depends_on:
            if dep in dependents:
                dependents[dep].append(task.position)

    ready = sorted(pos for pos, deg in in_degree.items() if deg == 0)
    batches: list[list[MissionTask]] = []
    processed = 0

    while ready:
        batch = [by_pos[p] for p in ready]
        batches.append(batch)
        processed += len(batch)

        next_ready: list[int] = []
        for p in ready:
            for child in dependents[p]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    next_ready.append(child)
        ready = sorted(next_ready)

    if processed != len(tasks):
        residue = sorted(pos for pos, deg in in_degree.items() if deg > 0)
        raise TaskGraphCycleError(f"Task graph'da sikl aniqlandi — Kahn qoldig'i: {residue}")

    return batches


def _synthesize(mission: Mission, tasks: Sequence[MissionTask]) -> str:
    """Mission-darajasidagi yakuniy hisobot — barcha taskning natijasi.

    Deterministik matn (LLM chaqirilmaydi) — har task holati + qisqa
    natija/xato bir qatorda. Bu — "final mission synthesis" talabining
    minimal, HALOL implementatsiyasi: LLM'ga "hammasi bilan xulosa yoz"
    deb topshirish JB-5 doirasidan tashqarida qoldirilgan (Brain-level
    xulosa yozish uchun `world_state`/`Brain` allaqachon mavjud — JB-2/3).
    """
    lines = [f"Mission: {mission.objective}"]
    for task in sorted(tasks, key=lambda t: t.position):
        marker = {
            StepStatus.DONE: "✓",
            StepStatus.FAILED: "✗",
            StepStatus.SKIPPED: "⊘",
        }.get(task.status, "?")
        detail = ""
        if task.status == StepStatus.DONE and task.result:
            detail = f" — {task.result[:200]}"
        elif task.status in (StepStatus.FAILED, StepStatus.SKIPPED) and task.error:
            detail = f" — {task.error[:200]}"
        lines.append(f"{marker} [{task.position}] {task.title}{detail}")
    return "\n".join(lines)


__all__ = [
    "CapabilityGap",
    "TaskGraphCycleError",
    "TaskGraphError",
    "TaskGraphExecutor",
    "TaskGraphResult",
]
