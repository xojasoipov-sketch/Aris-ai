"""AgentSelector — tool-qamrovga asoslangan HAQIQIY dinamik agent tanlash (JB-4).

MUAMMO (audit topilmasi #4, kod bilan tasdiqlangan):

    * `CapabilityRegistry.resolve()` capability'ning STATIK `default_agents`
      ro'yxatini qaytarardi — bu qiymat AgentRegistry'dagi haqiqiy holatni
      (agent ro'yxatdanmi, ACTIVE'mi) HECH QACHON tekshirmasdi. PAUSED yoki
      umuman ro'yxatdan o'tkazilmagan agent nomi ham xotirjam qaytardi.
    * `MissionTask.agent` maydoni BOR edi, lekin `_bundle_to_tasks()` uni
      HECH QACHON to'ldirmasdi — har doim `None`. "Qaysi agent qaysi
      vazifani oladi" degan qaror UMUMAN qabul qilinmasdi.
    * Natija: "dinamik agent tanlash" hujjatlarda va sxemada bor edi,
      amalda esa har joyda YO qattiq yozilgan nom (kunlik jadval), YO
      hech qanday agent tushunchasi ishlatilmasdi (asosiy chat oqimi).

Bu modul HAQIQIY qaror qabul qiladi: berilgan tool to'plami uchun,
AgentRegistry'dagi JORIY ACTIVE agentlar orasidan, `tool_allowlist`
QAMROVI bo'yicha eng mos agentni tanlaydi. Capability'ning
`default_agents`i endi faqat BOSHLANG'ICH TAKLIF (tezroq yaqinlashish
uchun) — yakuniy qaror har doim registrydagi HAQIQIY holatga qarab
qabul qilinadi.

Bog'liq qarorlar:
    JB-4 — dinamik agent tanlash (JARVIS Brain auditi §7, §24)
    V-11 — agent holat mashinasi (faqat ACTIVE tanlanadi)
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

import structlog

log = structlog.get_logger(__name__)


class _AgentStateLike(Protocol):
    """`AgentState`ning selector ishlatadigan qismi (test fake'lari uchun ham)."""

    @property
    def status(self) -> object: ...  # pragma: no cover — protocol

    @property
    def spec(self) -> object: ...  # pragma: no cover — protocol


class _AgentRegistryLike(Protocol):
    """`AgentRegistry`ning selector ishlatadigan qismi."""

    def list_agents(self, *, status: object | None = None) -> list[object]: ...  # pragma: no cover


@dataclass(frozen=True)
class AgentMatch:
    """Bitta agent nomzodining bahosi — nega tanlangani/tanlanmagani ko'rinsin."""

    agent_name: str
    covered_tools: tuple[str, ...]
    """Bu agent bajara oladigan (o'z `tool_allowlist`ida bor) toollar."""
    coverage_ratio: float
    """`len(covered_tools) / len(required_tools)` — 0 dan 1 gacha."""
    was_preferred: bool
    """Capability'ning `default_agents`ida bor edimi (boshlang'ich taklif)."""


@dataclass(frozen=True)
class SelectionResult:
    """`assign_tool_agents()` natijasi — qaror VA sababi birga."""

    tool_agents: dict[str, str] = field(default_factory=dict)
    """Har bir tool uchun tanlangan agent nomi. Topilmagan tool — kalitda yo'q."""

    unmatched_tools: tuple[str, ...] = ()
    """Hech qanday ACTIVE agent qamrab ololmagan toollar (halol holat)."""

    excluded_preferred: tuple[str, ...] = ()
    """Capability taklif qilgan-u ACTIVE bo'lmagani/ro'yxatda yo'qligi uchun
    chetlab o'tilgan agent nomlari — kuzatuv uchun (nima uchun boshqa agent
    tanlangani tushunarli bo'lsin)."""

    active_agents: tuple[str, ...] = ()
    """Yakuniy tanlovga kirgan barcha (unikal) agent nomlari."""


class AgentSelector:
    """`AgentRegistry` ustidan tool-qamrov bo'yicha real vaqtli tanlov.

    LLM EMAS — deterministik, tekshiriladigan qoida: agent nomzod
    bo'lishi uchun (1) ACTIVE holatda bo'lishi, (2) kerakli tool o'z
    `tool_allowlist`ida bo'lishi kerak. Ikkalasidan biri yo'q bo'lsa —
    nomzod emas, halol tarzda `unmatched_tools`/`excluded_preferred`ga
    yoziladi (o'ylab topilgan tayinlash yo'q).
    """

    def __init__(self, agent_registry: _AgentRegistryLike) -> None:
        self._registry = agent_registry

    def _active_agents(self) -> dict[str, frozenset[str]]:
        """ACTIVE agentlar → ularning tool_allowlist to'plami.

        Har chaqiruvda qayta o'qiladi (registry holati o'zgarishi mumkin —
        agent pauza/faollashtirilishi runtime'da bo'ladi, keshlash eskirgan
        qarorga olib kelardi)."""
        from zet.domain.enums import AgentStatus

        result: dict[str, frozenset[str]] = {}
        for state in self._registry.list_agents(status=AgentStatus.ACTIVE):
            spec = state.spec  # type: ignore[attr-defined]
            result[spec.name] = frozenset(spec.tool_allowlist)
        return result

    def rank_for_tools(
        self,
        required_tools: Sequence[str],
        *,
        preferred: Sequence[str] = (),
    ) -> list[AgentMatch]:
        """Barcha ACTIVE agentlarni berilgan toollar bo'yicha qamrov tartibida beradi.

        Tartib: (1) qamrov nisbati kamayish tartibida, (2) `preferred`da
        bor agentlar teng qamrovda ustuvor, (3) nom bo'yicha alifbo
        (barqaror natija — testlar va kuzatuv uchun muhim).
        """
        required = [t for t in required_tools if t]
        if not required:
            return []
        preferred_set = set(preferred)
        active = self._active_agents()

        matches: list[AgentMatch] = []
        for name, allowlist in active.items():
            covered = tuple(t for t in required if t in allowlist)
            if not covered:
                continue
            matches.append(
                AgentMatch(
                    agent_name=name,
                    covered_tools=covered,
                    coverage_ratio=len(covered) / len(required),
                    was_preferred=name in preferred_set,
                )
            )

        matches.sort(
            key=lambda m: (-m.coverage_ratio, not m.was_preferred, m.agent_name)
        )
        return matches

    def assign_tool_agents(
        self,
        required_tools: Sequence[str],
        *,
        preferred: Sequence[str] = (),
    ) -> SelectionResult:
        """Har bir tool uchun BITTA agent tanlaydi (Task Graph vazifasi uchun).

        Ochko'zlik strategiyasi: eng yuqori QAMROVLI agent birinchi
        navbatda qanchalik ko'p tool olishi mumkin bo'lsa oladi — bu
        vazifalarni kamroq agentga guruhlab, mission'ni bo'laklab
        yubormaydi (10 ta tool uchun 10 ta har xil agent emas, imkon
        qadar 1-2 ta izchil agent).
        """
        required = [t for t in required_tools if t]
        ranking = self.rank_for_tools(required, preferred=preferred)

        tool_agents: dict[str, str] = {}
        remaining = set(required)
        for match in ranking:
            if not remaining:
                break
            newly_covered = [t for t in match.covered_tools if t in remaining]
            for tool in newly_covered:
                tool_agents[tool] = match.agent_name
                remaining.discard(tool)

        active_names = self._active_agents()
        excluded_preferred = tuple(
            sorted(name for name in preferred if name and name not in active_names)
        )

        result = SelectionResult(
            tool_agents=tool_agents,
            unmatched_tools=tuple(sorted(remaining)),
            excluded_preferred=excluded_preferred,
            active_agents=tuple(sorted(set(tool_agents.values()))),
        )
        log.info(
            "agent_selector.assigned",
            required=len(required),
            matched=len(tool_agents),
            unmatched=len(result.unmatched_tools),
            excluded_preferred=len(excluded_preferred),
            agents=result.active_agents,
        )
        return result

    def filter_active(self, names: Sequence[str]) -> list[str]:
        """Berilgan nomlardan FAQAT haqiqatan ACTIVE bo'lganlarini qaytaradi.

        `CapabilityResolution.agents` kabi statik ro'yxatlarni Mission
        API'ga chiqarishdan oldin tozalash uchun — pauza/o'chirilgan
        agent nomi "tanlangan" bo'lib ko'rinmasin."""
        active = self._active_agents()
        return [n for n in names if n in active]


__all__ = ["AgentMatch", "AgentSelector", "SelectionResult"]
