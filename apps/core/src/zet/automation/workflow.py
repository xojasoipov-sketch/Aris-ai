"""Workflow Chain — ketma-ket agent zanjiri (Bo'lim 9).

Agent natijasi keyingi agentga uzatiladi.
Masalan: Research → CEO → Operations (hisobot zanjiri).

Xavfsizlik:
    - Har bir qadam alohida run sifatida bajariladi (A-07)
    - Zanjir uzunligi cheklangan (max 10 qadam)
    - Agar bitta qadam muvaffaqiyatsiz bo'lsa — zanjir to'xtaydi

Bog'liq qarorlar:
    Bo'lim 9 — avtomatlashtirish
    A-07 — har bir run uchun tormozlar
    V-32 — approval kerak bo'lsa zanjir kutadi
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)

# Zanjir chegarasi
MAX_CHAIN_STEPS = 10


class WorkflowStatus(StrEnum):
    """Workflow holati."""

    PENDING = "pending"
    """Hali boshlanmagan."""

    RUNNING = "running"
    """Ishlayapti."""

    COMPLETED = "completed"
    """Muvaffaqiyatli tugadi."""

    FAILED = "failed"
    """Xatolik bilan tugadi."""

    CANCELLED = "cancelled"
    """Bekor qilindi."""


class WorkflowStep(BaseModel, frozen=True):
    """Workflow qadami — bitta agentni bajarish.

    Oldingi qadam natijasi `input_text` sifatida kiritiladi.
    """

    agent_name: str = Field(min_length=1)
    """Bajariladigan agent nomi."""

    command_template: str = ""
    """Buyruq shabloni. {prev_output} oldingi natijani kiritadi."""

    timeout_s: int = Field(default=120, ge=10, le=600)
    """Qadam uchun vaqt chegarasi."""

    require_approval: bool = False
    """Bu qadamdan oldin approval kerakmi (V-32)."""

    # Runtime natijalar
    status: WorkflowStatus = WorkflowStatus.PENDING
    """Qadam holati."""

    output: str = ""
    """Qadam natijasi."""

    error: str | None = None
    """Xato xabari."""

    started_at: datetime | None = None
    """Boshlangan vaqt."""

    finished_at: datetime | None = None
    """Tugagan vaqt."""


class WorkflowChain(BaseModel, frozen=True):
    """Workflow zanjiri — ketma-ket agentlar bajarish.

    Qadamlar: step_0 → step_1 → ... → step_N
    Har bir qadam oldingi natijani oladi va o'z natijasini beradi.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    """Unikal workflow ID."""

    name: str = Field(min_length=1, max_length=100)
    """Workflow nomi."""

    description: str = ""
    """Workflow tavsifi."""

    steps: list[WorkflowStep] = Field(default_factory=list)
    """Qadamlar ketma-ketligi."""

    status: WorkflowStatus = WorkflowStatus.PENDING
    """Umumiy holat."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Yaratilgan vaqt."""

    started_at: datetime | None = None
    """Boshlangan vaqt."""

    finished_at: datetime | None = None
    """Tugagan vaqt."""

    @property
    def step_count(self) -> int:
        """Qadamlar soni."""
        return len(self.steps)

    @property
    def completed_steps(self) -> int:
        """Tugallangan qadamlar soni."""
        return sum(1 for s in self.steps if s.status == WorkflowStatus.COMPLETED)

    @property
    def current_step_index(self) -> int | None:
        """Joriy qadam indeksi (None agar bajarilmayotgan bo'lsa)."""
        for i, step in enumerate(self.steps):
            if step.status in {WorkflowStatus.PENDING, WorkflowStatus.RUNNING}:
                return i
        return None

    @property
    def progress(self) -> float:
        """Bajarilish foizi (0.0 — 1.0)."""
        if not self.steps:
            return 0.0
        return self.completed_steps / len(self.steps)

    @property
    def is_terminal(self) -> bool:
        """Yakuniy holatda."""
        return self.status in {
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }


def validate_chain(steps: list[WorkflowStep]) -> list[str]:
    """Workflow zanjirini validatsiya qilish.

    Args:
        steps: Qadamlar ro'yxati

    Returns:
        Xatolar ro'yxati (bo'sh = yaroqli)
    """
    errors: list[str] = []

    if not steps:
        errors.append("Zanjirda hech qanday qadam yo'q")

    if len(steps) > MAX_CHAIN_STEPS:
        errors.append(f"Zanjir juda uzun: {len(steps)} qadam (max {MAX_CHAIN_STEPS})")

    seen_agents: list[str] = []
    for i, step in enumerate(steps):
        if not step.agent_name:
            errors.append(f"Qadam {i}: agent nomi bo'sh")
        seen_agents.append(step.agent_name)

    return errors


class WorkflowRunner:
    """Workflow boshqaruvchisi (in-memory).

    Produksiyada DB bilan almashtiriladi.
    Haqiqiy agent bajarish alohida qatlamda (Orchestrator).
    """

    def __init__(self) -> None:
        self._workflows: dict[str, WorkflowChain] = {}

    def create(
        self,
        *,
        name: str,
        steps: list[WorkflowStep],
        description: str = "",
    ) -> WorkflowChain:
        """Yangi workflow yaratish.

        Args:
            name: Workflow nomi
            steps: Qadamlar
            description: Tavsif

        Returns:
            Yaratilgan workflow

        Raises:
            ValueError: Zanjir noto'g'ri
        """
        errors = validate_chain(steps)
        if errors:
            msg = f"Workflow validatsiya xatolari: {'; '.join(errors)}"
            raise ValueError(msg)

        chain = WorkflowChain(
            name=name,
            steps=steps,
            description=description,
        )
        self._workflows[chain.id] = chain
        log.info(
            "workflow.created",
            id=chain.id,
            name=name,
            steps=len(steps),
        )
        return chain

    def get(self, workflow_id: str) -> WorkflowChain | None:
        """Workflow olish."""
        return self._workflows.get(workflow_id)

    def list_workflows(self, *, status: WorkflowStatus | None = None) -> list[WorkflowChain]:
        """Workflowlar ro'yxati."""
        if status is None:
            return list(self._workflows.values())
        return [w for w in self._workflows.values() if w.status == status]

    def start(self, workflow_id: str) -> WorkflowChain | None:
        """Workflowni boshlash."""
        old = self._workflows.get(workflow_id)
        if old is None or old.status != WorkflowStatus.PENDING:
            return None

        # Birinchi qadamni RUNNING qilish
        new_steps = list(old.steps)
        if new_steps:
            new_steps[0] = WorkflowStep(
                agent_name=new_steps[0].agent_name,
                command_template=new_steps[0].command_template,
                timeout_s=new_steps[0].timeout_s,
                require_approval=new_steps[0].require_approval,
                status=WorkflowStatus.RUNNING,
                started_at=datetime.now(UTC),
            )

        updated = WorkflowChain(
            id=old.id,
            name=old.name,
            description=old.description,
            steps=new_steps,
            status=WorkflowStatus.RUNNING,
            created_at=old.created_at,
            started_at=datetime.now(UTC),
        )
        self._workflows[workflow_id] = updated
        log.info("workflow.started", id=workflow_id)
        return updated

    def complete_step(
        self, workflow_id: str, step_index: int, *, output: str
    ) -> WorkflowChain | None:
        """Qadamni tugatish va keyingisini boshlash.

        Args:
            workflow_id: Workflow ID
            step_index: Tugagan qadam indeksi
            output: Qadam natijasi

        Returns:
            Yangilangan workflow (None agar topilmasa)
        """
        old = self._workflows.get(workflow_id)
        if old is None or old.status != WorkflowStatus.RUNNING:
            return None
        if step_index < 0 or step_index >= len(old.steps):
            return None

        new_steps = list(old.steps)
        now = datetime.now(UTC)

        # Joriy qadamni COMPLETED qilish
        current = new_steps[step_index]
        new_steps[step_index] = WorkflowStep(
            agent_name=current.agent_name,
            command_template=current.command_template,
            timeout_s=current.timeout_s,
            require_approval=current.require_approval,
            status=WorkflowStatus.COMPLETED,
            output=output,
            started_at=current.started_at,
            finished_at=now,
        )

        # Keyingi qadam bormi?
        next_index = step_index + 1
        workflow_status = WorkflowStatus.RUNNING
        finished_at = None

        if next_index >= len(new_steps):
            # Barcha qadamlar tugadi
            workflow_status = WorkflowStatus.COMPLETED
            finished_at = now
        else:
            # Keyingi qadamni boshlash
            nxt = new_steps[next_index]
            new_steps[next_index] = WorkflowStep(
                agent_name=nxt.agent_name,
                command_template=nxt.command_template,
                timeout_s=nxt.timeout_s,
                require_approval=nxt.require_approval,
                status=WorkflowStatus.RUNNING,
                started_at=now,
            )

        updated = WorkflowChain(
            id=old.id,
            name=old.name,
            description=old.description,
            steps=new_steps,
            status=workflow_status,
            created_at=old.created_at,
            started_at=old.started_at,
            finished_at=finished_at,
        )
        self._workflows[workflow_id] = updated
        return updated

    def fail_step(self, workflow_id: str, step_index: int, *, error: str) -> WorkflowChain | None:
        """Qadamda xatolik — zanjirni to'xtatish.

        Args:
            workflow_id: Workflow ID
            step_index: Xato bo'lgan qadam indeksi
            error: Xato xabari

        Returns:
            Yangilangan workflow
        """
        old = self._workflows.get(workflow_id)
        if old is None or old.status != WorkflowStatus.RUNNING:
            return None
        if step_index < 0 or step_index >= len(old.steps):
            return None

        new_steps = list(old.steps)
        now = datetime.now(UTC)

        current = new_steps[step_index]
        new_steps[step_index] = WorkflowStep(
            agent_name=current.agent_name,
            command_template=current.command_template,
            timeout_s=current.timeout_s,
            require_approval=current.require_approval,
            status=WorkflowStatus.FAILED,
            error=error,
            started_at=current.started_at,
            finished_at=now,
        )

        updated = WorkflowChain(
            id=old.id,
            name=old.name,
            description=old.description,
            steps=new_steps,
            status=WorkflowStatus.FAILED,
            created_at=old.created_at,
            started_at=old.started_at,
            finished_at=now,
        )
        self._workflows[workflow_id] = updated
        log.info("workflow.failed", id=workflow_id, step=step_index, error=error)
        return updated

    def remove(self, workflow_id: str) -> bool:
        """Workflow o'chirish."""
        if workflow_id in self._workflows:
            del self._workflows[workflow_id]
            return True
        return False

    @property
    def stats(self) -> dict[str, int]:
        """Statistika."""
        wfs = list(self._workflows.values())
        return {
            "total": len(wfs),
            "pending": sum(1 for w in wfs if w.status == WorkflowStatus.PENDING),
            "running": sum(1 for w in wfs if w.status == WorkflowStatus.RUNNING),
            "completed": sum(1 for w in wfs if w.status == WorkflowStatus.COMPLETED),
            "failed": sum(1 for w in wfs if w.status == WorkflowStatus.FAILED),
        }
