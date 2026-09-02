"""Agent Lifecycle — V-11 holat mashinasi (Bo'lim 3).

Holat o'tishlari:
    DRAFT → TESTING → ACTIVE → PAUSED → DISABLED → ARCHIVED

Qoidalar:
    - DRAFT → TESTING: eval to'plami tayyor bo'lishi kerak (Bo'lim 4 da)
    - TESTING → ACTIVE: faqat egasi tasdig'i bilan
    - ACTIVE → PAUSED: vaqtincha to'xtatish
    - PAUSED → ACTIVE: qayta yoqish
    - * → DISABLED: xato yoki siyosat buzilishi
    - * → ARCHIVED: butunlay o'chirish

Bog'liq qarorlar:
    V-11 — lifecycle avtomati
    A-02 — agent = ma'lumot
"""

from __future__ import annotations

import structlog

from zet.agents.registry import AgentRegistry
from zet.domain.agent import AgentState
from zet.domain.enums import AgentStatus

log = structlog.get_logger(__name__)


class AgentLifecycleError(Exception):
    """Lifecycle o'tishi xatosi."""


class AgentLifecycle:
    """Agent lifecycle boshqaruvchisi (V-11).

    Registry ustiga qurilgan — status o'tishlarini boshqaradi.
    """

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    def activate(self, name: str) -> AgentState:
        """Agentni faollashtirish (TESTING → ACTIVE yoki PAUSED → ACTIVE).

        Raises:
            AgentLifecycleError: Noto'g'ri o'tish.
        """
        state = self._registry.get(name)
        if state.status not in {AgentStatus.TESTING, AgentStatus.PAUSED}:
            raise AgentLifecycleError(
                f"Agent '{name}' {state.status.value} dan ACTIVE ga o'ta olmaydi. "
                f"Faqat TESTING yoki PAUSED dan mumkin."
            )
        return self._registry.update_status(name, AgentStatus.ACTIVE)

    def start_testing(self, name: str) -> AgentState:
        """Agentni sinov bosqichiga o'tkazish (DRAFT → TESTING).

        Raises:
            AgentLifecycleError: Noto'g'ri o'tish.
        """
        state = self._registry.get(name)
        if state.status != AgentStatus.DRAFT:
            raise AgentLifecycleError(
                f"Agent '{name}' {state.status.value} dan TESTING ga o'ta olmaydi. "
                f"Faqat DRAFT dan mumkin."
            )
        return self._registry.update_status(name, AgentStatus.TESTING)

    def pause(self, name: str) -> AgentState:
        """Agentni vaqtincha to'xtatish (ACTIVE → PAUSED).

        Raises:
            AgentLifecycleError: Noto'g'ri o'tish.
        """
        state = self._registry.get(name)
        if state.status != AgentStatus.ACTIVE:
            raise AgentLifecycleError(
                f"Agent '{name}' {state.status.value} dan PAUSED ga o'ta olmaydi. "
                f"Faqat ACTIVE dan mumkin."
            )
        return self._registry.update_status(name, AgentStatus.PAUSED)

    def disable(self, name: str, *, reason: str = "") -> AgentState:
        """Agentni o'chirish (xato yoki siyosat buzilishi).

        TESTING, ACTIVE, PAUSED dan mumkin.

        Raises:
            AgentLifecycleError: Noto'g'ri o'tish.
        """
        state = self._registry.get(name)
        allowed_from = {AgentStatus.TESTING, AgentStatus.ACTIVE, AgentStatus.PAUSED}
        if state.status not in allowed_from:
            raise AgentLifecycleError(
                f"Agent '{name}' {state.status.value} dan DISABLED ga o'ta olmaydi."
            )

        if reason:
            log.warning("agent.disabled", name=name, reason=reason)

        return self._registry.update_status(name, AgentStatus.DISABLED)

    def archive(self, name: str) -> AgentState:
        """Agentni arxivlash (qaytmas terminal holat).

        Har qanday holatdan mumkin (ARCHIVED dan tashqari).

        Raises:
            AgentLifecycleError: Allaqachon arxivlangan.
        """
        state = self._registry.get(name)
        if state.status == AgentStatus.ARCHIVED:
            raise AgentLifecycleError(f"Agent '{name}' allaqachon arxivlangan")
        return self._registry.update_status(name, AgentStatus.ARCHIVED)

    def reset_to_draft(self, name: str) -> AgentState:
        """Agentni qoralamaga qaytarish (DISABLED → DRAFT).

        Tuzatish va qayta sinov uchun.

        Raises:
            AgentLifecycleError: Noto'g'ri o'tish.
        """
        state = self._registry.get(name)
        if state.status != AgentStatus.DISABLED:
            raise AgentLifecycleError(
                f"Agent '{name}' {state.status.value} dan DRAFT ga o'ta olmaydi. "
                f"Faqat DISABLED dan mumkin."
            )
        return self._registry.update_status(name, AgentStatus.DRAFT)
