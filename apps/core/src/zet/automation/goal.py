"""Mustaqil maqsad tsikli — agentning 5-xususiyati (yangi zip, slayd 10).

Ega ta'rifi: *"Mustaqillik [self-planning] — maqsad qo'yiladi; maqsadga
yetmasa qayta rejalashtiradi va o'zini yaxshilaydi, yetguncha takrorlaydi."*

Bu `deploy/selfimprove.py`dan **boshqa narsa**. U tizim haqida ega uchun
tavsiya yozadi ("shu agent qimmat, modelini almashtiring") va hech narsani
o'zgartirmaydi. Bu modul esa **bitta maqsad ustida yopiq tsikl**:

    reja → bajarish → baholash → yetmadimi? → tanqidni hisobga olib qayta reja

Tsikl `AutonomyLevel` bilan chegaralanadi — bu tasodifiy emas, asosiy
xavfsizlik chizig'i:

    L0-L2  → maqsad tsikli umuman yo'q (`SELF_PLANNING` yo'q)
    L3     → 1 urinish (rejalashtiradi, lekin qayta urinmaydi)
    L4     → 5 urinishgacha (`SELF_IMPROVE` — tanqiddan o'rganib qayta urinadi)

BAHOLASH KONSERVATIV. Baholovchi javobini o'qib bo'lmasa, tizim
"yetmadi" deb hisoblaydi. Noaniqlikda g'alaba e'lon qilish — avtonom
tizimda eng qimmat xato: ega ish bitgan deb o'ylab, tekshirmay qoladi.

V-32 KUCHDA. Tsikl faqat *rejalashtirishda* mustaqil. EXECUTE amal
baribir tasdiqdan o'tadi — L4 buni chetlab o'tmaydi.

Bog'liq qarorlar:
    Yangi zip — 5-xususiyat (mustaqillik), L4 daraja
    A-07 — run tormozlari (iteratsiya chegarasi)
    V-32 — majburiy tasdiq
    V-36 — self-improvement (qo'shni, lekin boshqa modul)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

import structlog
from pydantic import BaseModel, Field

from zet.agents.registry import AgentRegistry
from zet.automation.autonomy import (
    AutonomyCapability,
    AutonomyLevel,
    max_goal_iterations,
    require,
)
from zet.automation.executor import AgentUnavailableError, run_agent_command
from zet.llm.base import LLMProvider
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.tools.registry import ToolRegistry

log = structlog.get_logger(__name__)

ACHIEVED_MARKER = "ACHIEVED"
"""Baholovchi javobi shu bilan boshlansa — maqsadga yetildi."""

NOT_ACHIEVED_MARKER = "NOT_ACHIEVED"
"""Baholovchi javobi shu bilan boshlansa — yetilmadi."""

MAX_CRITIQUE_LEN = 2000
"""Keyingi rejaga uzatiladigan tanqidning maksimal uzunligi."""


class GoalStatus(StrEnum):
    """Maqsad holati."""

    PENDING = "pending"
    """Hali boshlanmagan."""

    RUNNING = "running"
    """Tsikl ishlayapti."""

    ACHIEVED = "achieved"
    """Maqsadga yetildi."""

    EXHAUSTED = "exhausted"
    """Urinishlar tugadi, maqsadga yetilmadi."""

    FAILED = "failed"
    """Texnik xato (agent yo'q, timeout) — tsikl to'xtadi."""

    STOPPED = "stopped"
    """Tashqaridan to'xtatildi (kill-switch yoki ega)."""


class GoalIteration(BaseModel, frozen=True):
    """Bitta urinish — reja, natija va baho."""

    index: int = Field(ge=0)
    """Urinish raqami (0 dan)."""

    command: str
    """Agentga yuborilgan buyruq (reja)."""

    output: str = ""
    """Agent natijasi."""

    achieved: bool = False
    """Baholovchi maqsadga yetildi dedimi."""

    critique: str = ""
    """Nega yetilmadi — keyingi rejaga kiritiladi."""

    error: str | None = None
    """Texnik xato (bo'lsa)."""

    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Boshlangan vaqt."""

    finished_at: datetime | None = None
    """Tugagan vaqt."""


class Goal(BaseModel, frozen=True):
    """Maqsad — natija aytiladi, yo'l aytilmaydi."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    """Unikal maqsad ID."""

    name: str = Field(min_length=1, max_length=100)
    """Maqsad nomi."""

    outcome: str = Field(min_length=1, max_length=2000)
    """Kutilayotgan NATIJA (nima bo'lishi kerak, qanday emas)."""

    success_criteria: str = Field(default="", max_length=2000)
    """Muvaffaqiyat mezoni — baholovchi shunga qarab hukm qiladi."""

    agent_name: str = Field(min_length=1)
    """Maqsad ustida ishlaydigan agent."""

    evaluator_agent: str = ""
    """Baholovchi agent. Bo'sh bo'lsa — agentning o'zi (o'z-o'zini baholash)."""

    autonomy_level: AutonomyLevel = AutonomyLevel.L3_AGENT
    """Avtonomiya darajasi — necha marta qayta urinishni belgilaydi."""

    status: GoalStatus = GoalStatus.PENDING
    """Joriy holat."""

    iterations: list[GoalIteration] = Field(default_factory=list)
    """Barcha urinishlar tarixi."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Yaratilgan vaqt."""

    finished_at: datetime | None = None
    """Tsikl tugagan vaqt."""

    @property
    def attempt_limit(self) -> int:
        """Ruxsat etilgan urinishlar soni (darajadan)."""
        return max_goal_iterations(self.autonomy_level)

    @property
    def attempts_used(self) -> int:
        """Sarflangan urinishlar."""
        return len(self.iterations)

    @property
    def is_terminal(self) -> bool:
        """Tsikl tugaganmi."""
        return self.status in {
            GoalStatus.ACHIEVED,
            GoalStatus.EXHAUSTED,
            GoalStatus.FAILED,
            GoalStatus.STOPPED,
        }


def build_command(goal: Goal, *, previous: GoalIteration | None) -> str:
    """Urinish uchun buyruq matnini yasash.

    Birinchi urinish — sof maqsad. Keyingilari — oldingi urinish tanqidi
    bilan ("o'zini yaxshilash" shu yerda sodir bo'ladi).
    """
    parts = [f"MAQSAD: {goal.outcome}"]
    if goal.success_criteria:
        parts.append(f"MUVAFFAQIYAT MEZONI: {goal.success_criteria}")

    if previous is not None:
        parts.append(
            f"OLDINGI URINISH ({previous.index + 1}-urinish) MAQSADGA YETMADI.\n"
            f"Nima qilingan edi: {previous.output[:MAX_CRITIQUE_LEN]}\n"
            f"Nega yetmadi: {previous.critique[:MAX_CRITIQUE_LEN]}\n"
            "Shu kamchilikni hisobga olib BOSHQA yo'l bilan urinib ko'r — "
            "oldingi qadamlarni aynan takrorlama."
        )

    parts.append("Natijani qisqa va aniq yoz.")
    return "\n\n".join(parts)


def build_evaluation_command(goal: Goal, output: str) -> str:
    """Baholovchi uchun buyruq — qat'iy formatda javob so'raydi."""
    criteria = goal.success_criteria or goal.outcome
    return (
        "Quyidagi ish natijasi maqsadga yetdimi — baho ber.\n\n"
        f"MAQSAD: {goal.outcome}\n"
        f"MUVAFFAQIYAT MEZONI: {criteria}\n\n"
        f"ISH NATIJASI:\n{output}\n\n"
        f"Javobingni ANIQ shu ikki so'zdan biri bilan BOSHLA: "
        f"'{ACHIEVED_MARKER}' yoki '{NOT_ACHIEVED_MARKER}'. "
        "So'ngra bir-ikki jumlada sababini yoz. Yetmagan bo'lsa — "
        "aynan nima yetishmaganini ayt."
    )


def parse_evaluation(text: str) -> tuple[bool, str]:
    """Baholovchi javobini o'qish.

    Returns:
        (yetildimi, tanqid matni)

    O'qib bo'lmasa — `(False, ...)`. Noaniqlikda muvaffaqiyat e'lon
    qilinmaydi: yolg'on "bajarildi" eng qimmat xato.
    """
    stripped = text.strip()
    upper = stripped.upper()

    # NOT_ACHIEVED avval tekshiriladi — u ACHIEVED ni ichiga oladi.
    if upper.startswith(NOT_ACHIEVED_MARKER):
        return False, stripped[len(NOT_ACHIEVED_MARKER) :].lstrip(" :—-\n") or "sabab yozilmadi"
    if upper.startswith(ACHIEVED_MARKER):
        return True, stripped[len(ACHIEVED_MARKER) :].lstrip(" :—-\n")

    log.warning("goal.evaluation_unparsed", preview=stripped[:120])
    return False, (
        "Baholovchi javobini o'qib bo'lmadi (kutilgan format: "
        f"'{ACHIEVED_MARKER}' yoki '{NOT_ACHIEVED_MARKER}' bilan boshlanishi). "
        f"Javob: {stripped[:500]}"
    )


class GoalPursuit:
    """Maqsad tsiklini yurituvchi.

    Har bir urinish: agentni ishga tushirish → baholash → yetmasa
    tanqid bilan qayta urinish. Chegara — `AutonomyLevel`.
    """

    def __init__(
        self,
        *,
        agent_registry: AgentRegistry,
        tool_registry: ToolRegistry,
        permission_policy: PermissionPolicy,
        killswitch: KillSwitchState | None = None,
        provider: LLMProvider | None = None,
    ) -> None:
        self._agent_registry = agent_registry
        self._tool_registry = tool_registry
        self._permission_policy = permission_policy
        self._killswitch = killswitch
        self._provider = provider

    async def pursue(self, goal: Goal) -> Goal:
        """Maqsadni yetgunicha (yoki urinishlar tugagunicha) quvish.

        Raises:
            AutonomyViolationError: daraja maqsad tsikliga ruxsat bermaydi
        """
        require(
            goal.autonomy_level,
            AutonomyCapability.SELF_PLANNING,
            subject=goal.agent_name,
        )

        limit = goal.attempt_limit
        iterations: list[GoalIteration] = []
        status = GoalStatus.RUNNING
        previous: GoalIteration | None = None

        for index in range(limit):
            if index > 0:
                # Qayta urinish = o'zini yaxshilash; bu faqat L4'da bor.
                require(
                    goal.autonomy_level,
                    AutonomyCapability.SELF_IMPROVE,
                    subject=goal.agent_name,
                )

            if self._killswitch is not None and self._killswitch.is_engaged:
                log.info("goal.stopped", goal_id=goal.id, reason="killswitch")
                status = GoalStatus.STOPPED
                break

            iteration = await self._attempt(goal, index=index, previous=previous)
            iterations.append(iteration)

            if iteration.error is not None:
                status = GoalStatus.FAILED
                break
            if iteration.achieved:
                status = GoalStatus.ACHIEVED
                break

            previous = iteration
            log.info(
                "goal.retry",
                goal_id=goal.id,
                attempt=index + 1,
                limit=limit,
                critique=iteration.critique[:200],
            )
        else:
            status = GoalStatus.EXHAUSTED

        log.info(
            "goal.finished",
            goal_id=goal.id,
            status=status.value,
            attempts=len(iterations),
            limit=limit,
        )
        return goal.model_copy(
            update={
                "status": status,
                "iterations": iterations,
                "finished_at": datetime.now(UTC),
            }
        )

    async def _attempt(
        self, goal: Goal, *, index: int, previous: GoalIteration | None
    ) -> GoalIteration:
        """Bitta urinish — bajarish va baholash."""
        command = build_command(goal, previous=previous)
        started = datetime.now(UTC)

        try:
            result = await run_agent_command(
                goal.agent_name,
                command,
                agent_registry=self._agent_registry,
                tool_registry=self._tool_registry,
                permission_policy=self._permission_policy,
                provider=self._provider,
            )
        except AgentUnavailableError as exc:
            return GoalIteration(
                index=index,
                command=command,
                error=str(exc),
                started_at=started,
                finished_at=datetime.now(UTC),
            )

        if not result.success:
            return GoalIteration(
                index=index,
                command=command,
                output=result.output,
                achieved=False,
                critique=result.error or "agent muvaffaqiyatsiz tugadi",
                started_at=started,
                finished_at=datetime.now(UTC),
            )

        achieved, critique = await self._evaluate(goal, result.output)
        return GoalIteration(
            index=index,
            command=command,
            output=result.output,
            achieved=achieved,
            critique=critique,
            started_at=started,
            finished_at=datetime.now(UTC),
        )

    async def _evaluate(self, goal: Goal, output: str) -> tuple[bool, str]:
        """Natijani baholash. Baholovchi ishlamasa — 'yetmadi' deb hisoblanadi."""
        evaluator = goal.evaluator_agent or goal.agent_name
        try:
            verdict = await run_agent_command(
                evaluator,
                build_evaluation_command(goal, output),
                agent_registry=self._agent_registry,
                tool_registry=self._tool_registry,
                permission_policy=self._permission_policy,
                provider=self._provider,
            )
        except AgentUnavailableError as exc:
            return False, f"baholovchi agent ishlamadi: {exc}"

        if not verdict.success:
            return False, f"baholash muvaffaqiyatsiz: {verdict.error or 'sababsiz'}"

        return parse_evaluation(verdict.output)


class GoalRegistry:
    """Maqsadlar registri (xotirada, boshqa registrlar bilan bir uslubda)."""

    def __init__(self) -> None:
        self._goals: dict[str, Goal] = {}

    def add(self, goal: Goal) -> Goal:
        """Yangi maqsad."""
        self._goals[goal.id] = goal
        log.info(
            "goal.added",
            id=goal.id,
            name=goal.name,
            agent=goal.agent_name,
            level=goal.autonomy_level.value,
        )
        return goal

    def get(self, goal_id: str) -> Goal | None:
        """Maqsadni olish."""
        return self._goals.get(goal_id)

    def save(self, goal: Goal) -> Goal:
        """Yangilangan maqsadni saqlash."""
        self._goals[goal.id] = goal
        return goal

    def list_goals(self, *, status: GoalStatus | None = None) -> list[Goal]:
        """Maqsadlar ro'yxati."""
        goals = list(self._goals.values())
        if status is None:
            return goals
        return [g for g in goals if g.status == status]

    def remove(self, goal_id: str) -> bool:
        """Maqsadni o'chirish."""
        if goal_id in self._goals:
            del self._goals[goal_id]
            return True
        return False

    @property
    def stats(self) -> dict[str, int]:
        """Statistika."""
        goals = list(self._goals.values())
        return {
            "total": len(goals),
            "running": sum(1 for g in goals if g.status == GoalStatus.RUNNING),
            "achieved": sum(1 for g in goals if g.status == GoalStatus.ACHIEVED),
            "exhausted": sum(1 for g in goals if g.status == GoalStatus.EXHAUSTED),
            "failed": sum(1 for g in goals if g.status == GoalStatus.FAILED),
        }


__all__ = [
    "ACHIEVED_MARKER",
    "NOT_ACHIEVED_MARKER",
    "Goal",
    "GoalIteration",
    "GoalPursuit",
    "GoalRegistry",
    "GoalStatus",
    "build_command",
    "build_evaluation_command",
    "parse_evaluation",
]
