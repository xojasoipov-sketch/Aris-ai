"""Agent Registry — agentlarni ro'yxatga olish va topish (Bo'lim 3).

ToolRegistry bilan parallel: agentlar ham allowlist orqali ishlaydi.
Faqat ro'yxatga olingan agentlar ishga tushirilishi mumkin.

Bog'liq qarorlar:
    A-02 — agent = ma'lumot
    V-11 — faqat ACTIVE agentlar ishga tushadi
"""

from __future__ import annotations

import structlog

from zet.domain.agent import AgentSpec, AgentState
from zet.domain.enums import AgentStatus

log = structlog.get_logger(__name__)


class AgentNotFoundError(Exception):
    """Registry'da bunday agent yo'q."""


class AgentNotActiveError(Exception):
    """Agent ACTIVE holatda emas — ishga tushirib bo'lmaydi."""


class AgentRegistry:
    """Agentlarni ro'yxatga olish va topish.

    In-memory implementation — Bo'lim 3 uchun yetarli.
    Postgres-backed versiya keyingi bo'limlarda.
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentState] = {}

    def register(self, spec: AgentSpec, *, status: AgentStatus = AgentStatus.DRAFT) -> AgentState:
        """Yangi agentni ro'yxatga oladi.

        Args:
            spec: Agent spetsifikatsiyasi.
            status: Boshlang'ich holat (default: DRAFT).

        Returns:
            Yaratilgan AgentState.

        Raises:
            ValueError: Agar shu nomda agent allaqachon mavjud.
        """
        if spec.name in self._agents:
            raise ValueError(f"Agent '{spec.name}' allaqachon ro'yxatda")

        state = AgentState(spec=spec, status=status, id=spec.name)
        self._agents[spec.name] = state

        log.info(
            "agent.registered",
            name=spec.name,
            status=status.value,
            tools=len(spec.tool_allowlist),
        )
        return state

    def get(self, name: str) -> AgentState:
        """Nom bo'yicha agentni topadi.

        Raises:
            AgentNotFoundError: registry'da yo'q.
        """
        try:
            return self._agents[name]
        except KeyError as exc:
            raise AgentNotFoundError(f"Agent '{name}' registry'da topilmadi") from exc

    def get_active(self, name: str) -> AgentState:
        """Faqat ACTIVE agentni topadi.

        Raises:
            AgentNotFoundError: yo'q.
            AgentNotActiveError: ACTIVE emas.
        """
        state = self.get(name)
        if state.status != AgentStatus.ACTIVE:
            raise AgentNotActiveError(
                f"Agent '{name}' {state.status.value} holatda — faqat ACTIVE agent ishga tushadi"
            )
        return state

    def list_agents(self, *, status: AgentStatus | None = None) -> list[AgentState]:
        """Barcha agentlar (ixtiyoriy status filtri bilan).

        Args:
            status: Faqat shu holatdagi agentlar (None = barchasi).
        """
        agents = list(self._agents.values())
        if status is not None:
            agents = [a for a in agents if a.status == status]
        return agents

    def has(self, name: str) -> bool:
        """Agent mavjudligini tekshiradi."""
        return name in self._agents

    def update_status(self, name: str, new_status: AgentStatus) -> AgentState:
        """Agent holatini yangilaydi.

        Transition V-11 ga muvofiq tekshiriladi.

        Raises:
            AgentNotFoundError: yo'q.
            ValueError: Noto'g'ri o'tish.
        """
        state = self.get(name)

        if not state.status.can_transition_to(new_status):
            raise ValueError(
                f"Agent '{name}': {state.status.value} → {new_status.value} o'tishi mumkin emas"
            )

        updated = AgentState(
            spec=state.spec,
            status=new_status,
            id=state.id,
            created_at=state.created_at,
            updated_at=state.updated_at,
            total_runs=state.total_runs,
            successful_runs=state.successful_runs,
            failed_runs=state.failed_runs,
            total_tool_calls=state.total_tool_calls,
        )
        self._agents[name] = updated

        log.info(
            "agent.status_changed",
            name=name,
            old=state.status.value,
            new=new_status.value,
        )
        return updated

    def record_run(self, name: str, *, success: bool, tool_calls: int = 0) -> AgentState:
        """Agent run natijasini qayd qiladi (metrikalar uchun).

        Args:
            name: Agent nomi.
            success: Muvaffaqiyatli bajarildi.
            tool_calls: Tool chaqiruvlari soni.
        """
        state = self.get(name)
        updated = AgentState(
            spec=state.spec,
            status=state.status,
            id=state.id,
            created_at=state.created_at,
            updated_at=state.updated_at,
            total_runs=state.total_runs + 1,
            successful_runs=state.successful_runs + (1 if success else 0),
            failed_runs=state.failed_runs + (0 if success else 1),
            total_tool_calls=state.total_tool_calls + tool_calls,
        )
        self._agents[name] = updated
        return updated

    @property
    def count(self) -> int:
        """Ro'yxatdagi agentlar soni."""
        return len(self._agents)
