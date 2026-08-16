"""World State — ZET ishlayotgan muhitning joriy manzarasi (JB-3).

MUAMMO (audit topilmasi #8, kod bilan tasdiqlangan):

ZET reja tuzayotganda "dunyoni ko'rmasdi".

    * Birlashtirilgan holat modeli UMUMAN yo'q edi — `CoreState` faqat
      uxlayapti/ishlayapti bayrog'i, boshqa hech narsa;
    * `ContextEngine` topgan kontekst `Mission.context`ga yozilardi,
      lekin `CapabilityRegistryComposer.compose()` uni birinchi qatorda
      `del context` bilan TASHLAB yuborardi — hech qanday LLM promptiga
      kirmasdi;
    * `Planner` faqat intent + tool imzolari + suhbat tarixini ko'rardi:
      qanday loyihalar bor, qaysi vazifalar ochiq, qaysi tasdiq
      kutmoqda, budjetdan qancha qolgan — bularning hech biri modelga
      yetmasdi.

Natijada "bugun nimaga e'tibor berishim kerak?" degan savolga ZET yo
tool'larni birma-bir chaqirib topishga urinardi, yo javobni umuman
o'ylab topardi.

FALSAFA — HALOL HOLAT (repo bo'ylab bir xil naqsh, `automation/
recipes.py` dagi `MISSING_CAPABILITY` bilan bir xil): manba
o'qilmasa, u BO'SH deb ko'rsatilmaydi. `unavailable` ro'yxatiga
tushadi va promptda ochiq "o'qib bo'lmadi" deb yoziladi. Model
"vazifa yo'q" bilan "vazifalarni ko'ra olmadim"ni ajratishi shart —
aks holda ishonchli ko'rinishdagi to'qima chiqadi.

Bog'liq qarorlar:
    JB-3 — World State (JARVIS Brain auditi §11)
    V-33 — killswitch holati
    ADR-0006 — budjet chegaralari
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)

_MAX_ITEMS = 5
"""Har bo'limdan promptga tushadigan maksimal element soni.

Butun ro'yxat emas — SANOQ + eng muhim bir nechtasi. Sabab: bu blok
HAR bir rejalashtirish chaqiruviga qo'shiladi, ya'ni uzunligi
to'g'ridan-to'g'ri har so'rovning narxiga aylanadi."""


class WorldState(BaseModel, frozen=True):
    """Muhitning bir lahzalik kesimi — rejalashtirishga kirish ma'lumoti."""

    core_mode: str = "active"
    """`CoreState` rejimi: active / sleeping."""

    killswitch_engaged: bool = False
    """Favqulodda to'xtatish yoqilganmi (V-33)."""

    autonomy_level: str | None = None
    """Ega sozlagan avtonomiya darajasi (ma'lum bo'lsa)."""

    open_tasks: int = 0
    """Bajarilmagan vazifalar soni."""

    task_titles: list[str] = Field(default_factory=list)
    """Eng yaqin bir nechta ochiq vazifa sarlavhasi."""

    active_projects: int = 0
    """Faol loyihalar soni."""

    project_names: list[str] = Field(default_factory=list)
    """Faol loyiha nomlari (qisqartirilgan ro'yxat)."""

    active_missions: int = 0
    """Tugamagan mission'lar soni."""

    mission_objectives: list[str] = Field(default_factory=list)
    """Tugamagan mission maqsadlari (qisqartirilgan)."""

    pending_approvals: int = 0
    """Ega tasdig'ini kutayotgan amallar soni."""

    active_agents: int = 0
    """ACTIVE holatidagi agentlar soni."""

    unhealthy_agents: list[str] = Field(default_factory=list)
    """Muammoli agentlar — ko'p yiqilgan yoki ACTIVE bo'lmaganlari."""

    budget_spent_today_usd: float | None = None
    """Bugungi sarf (o'qilmasa `None` — nol EMAS)."""

    budget_remaining_month_usd: float | None = None
    """Oylik limitdan qolgan mablag'."""

    unavailable: list[str] = Field(default_factory=list)
    """O'QIB BO'LMAGAN manbalar — halol holat uchun.

    Bu ro'yxat bo'sh emasligini model KO'RISHI kerak: "vazifa yo'q"
    bilan "vazifalarni o'qiy olmadim" bir xil narsa emas."""

    def to_prompt_block(self) -> str:
        """LLM promptiga qo'shiladigan ixcham matn.

        JSON EMAS: model uchun tabiiy til qatorlari arzonroq va
        aniqroq o'qiladi. Bo'sh/nolga teng bo'limlar umuman
        yozilmaydi — keraksiz token sarflamaslik uchun.
        """
        lines: list[str] = []

        if self.killswitch_engaged:
            lines.append("- FAVQULODDA TO'XTATISH YOQILGAN — hech qanday amal bajarilmaydi.")
        if self.core_mode != "active":
            lines.append(f"- Rejim: {self.core_mode} (proaktiv ishlar to'xtatilgan).")
        if self.autonomy_level:
            lines.append(f"- Avtonomiya darajasi: {self.autonomy_level}.")

        if self.active_projects:
            names = ", ".join(self.project_names) if self.project_names else ""
            suffix = f" ({names})" if names else ""
            lines.append(f"- Faol loyihalar: {self.active_projects}{suffix}.")

        if self.open_tasks:
            titles = "; ".join(self.task_titles) if self.task_titles else ""
            suffix = f" — masalan: {titles}" if titles else ""
            lines.append(f"- Ochiq vazifalar: {self.open_tasks}{suffix}.")

        if self.active_missions:
            objectives = "; ".join(self.mission_objectives) if self.mission_objectives else ""
            suffix = f" — {objectives}" if objectives else ""
            lines.append(f"- Tugamagan mission'lar: {self.active_missions}{suffix}.")

        if self.pending_approvals:
            lines.append(f"- Tasdiq kutayotgan amallar: {self.pending_approvals}.")

        if self.active_agents:
            lines.append(f"- Faol agentlar: {self.active_agents}.")
        if self.unhealthy_agents:
            lines.append(f"- Muammoli agentlar: {', '.join(self.unhealthy_agents)}.")

        if self.budget_spent_today_usd is not None:
            spent = f"${self.budget_spent_today_usd:.2f}"
            if self.budget_remaining_month_usd is not None:
                lines.append(
                    f"- Budjet: bugun {spent} sarflandi, "
                    f"oylik limitdan ${self.budget_remaining_month_usd:.2f} qoldi."
                )
            else:
                lines.append(f"- Budjet: bugun {spent} sarflandi.")

        if self.unavailable:
            lines.append(
                f"- O'QIB BO'LMADI: {', '.join(self.unavailable)}. "
                "Bu manbalar haqida hech narsa DA'VO QILMA — "
                "\"bilmayman\" deb ayt yoki tegishli tool bilan tekshir."
            )

        if not lines:
            return ""
        return "HOZIRGI HOLAT (tizim bergan haqiqiy ma'lumot):\n" + "\n".join(lines)


class WorldStateBuilder:
    """Mavjud manbalardan `WorldState` yig'adi — har biri alohida fail-open.

    Bitta manba yiqilsa qolganlari baribir to'planadi; yiqilgani
    `unavailable`ga yoziladi. Butun blok yiqilib run'ni to'xtatishi
    MUMKIN EMAS — bu qo'shimcha kontekst, majburiy bosqich emas.
    """

    def __init__(
        self,
        *,
        core_state: Any = None,
        killswitch: Any = None,
        agent_registry: Any = None,
        approvals: Any = None,
        workspace: Any = None,
        mission_repo: Any = None,
        budget_snapshot: Callable[[], Awaitable[Any]] | None = None,
        autonomy_level: str | None = None,
    ) -> None:
        self._core_state = core_state
        self._killswitch = killswitch
        self._agents = agent_registry
        self._approvals = approvals
        self._workspace = workspace
        self._missions = mission_repo
        self._budget_snapshot = budget_snapshot
        self._autonomy_level = autonomy_level

    async def build(self) -> WorldState:
        """Barcha manbalarni o'qib bitta kesim qaytaradi."""
        unavailable: list[str] = []
        data: dict[str, Any] = {"autonomy_level": self._autonomy_level}

        self._read_core(data, unavailable)
        self._read_agents(data, unavailable)
        self._read_approvals(data, unavailable)
        await self._read_workspace(data, unavailable)
        await self._read_missions(data, unavailable)
        await self._read_budget(data, unavailable)

        data["unavailable"] = unavailable
        state = WorldState(**data)
        log.info(
            "world_state.built",
            open_tasks=state.open_tasks,
            active_projects=state.active_projects,
            active_missions=state.active_missions,
            pending_approvals=state.pending_approvals,
            unavailable=len(unavailable),
        )
        return state

    # ── Manba o'quvchilari ───────────────────────────────────────

    def _read_core(self, data: dict[str, Any], unavailable: list[str]) -> None:
        if self._core_state is not None:
            try:
                data["core_mode"] = self._core_state.mode.value
            except Exception:
                unavailable.append("tizim rejimi")
        if self._killswitch is not None:
            try:
                data["killswitch_engaged"] = bool(self._killswitch.is_engaged)
            except Exception:
                unavailable.append("killswitch holati")

    def _read_agents(self, data: dict[str, Any], unavailable: list[str]) -> None:
        if self._agents is None:
            return
        try:
            from zet.domain.enums import AgentStatus

            states = self._agents.list_agents()
            data["active_agents"] = sum(1 for s in states if s.status == AgentStatus.ACTIVE)
            # "Muammoli" = yarmidan ko'pi yiqilgan (kamida 2 ta run bo'lsa).
            # Bitta yiqilishdan shovqin qilmaymiz.
            data["unhealthy_agents"] = [
                s.spec.name
                for s in states
                if s.total_runs >= 2 and s.failed_runs * 2 > s.total_runs
            ][:_MAX_ITEMS]
        except Exception:
            unavailable.append("agent holati")

    def _read_approvals(self, data: dict[str, Any], unavailable: list[str]) -> None:
        if self._approvals is None:
            return
        try:
            data["pending_approvals"] = len(self._approvals.all_pending())
        except Exception:
            unavailable.append("kutilayotgan tasdiqlar")

    async def _read_workspace(self, data: dict[str, Any], unavailable: list[str]) -> None:
        if self._workspace is None:
            return
        try:
            from zet.domain.workspace import TaskStatus

            tasks = await self._workspace.list_tasks(status=TaskStatus.TODO)
            data["open_tasks"] = len(tasks)
            data["task_titles"] = [t.title for t in tasks[:_MAX_ITEMS]]
        except Exception:
            unavailable.append("vazifalar")

        try:
            from zet.domain.workspace import ProjectStatus

            projects = await self._workspace.list_projects(status=ProjectStatus.ACTIVE)
            data["active_projects"] = len(projects)
            data["project_names"] = [p.name for p in projects[:_MAX_ITEMS]]
        except Exception:
            unavailable.append("loyihalar")

    async def _read_missions(self, data: dict[str, Any], unavailable: list[str]) -> None:
        if self._missions is None:
            return
        try:
            rows = await self._missions.list(limit=50)
            active = [m for m in rows if not m.status.is_terminal]
            data["active_missions"] = len(active)
            data["mission_objectives"] = [m.objective[:80] for m in active[:_MAX_ITEMS]]
        except Exception:
            unavailable.append("mission'lar")

    async def _read_budget(self, data: dict[str, Any], unavailable: list[str]) -> None:
        if self._budget_snapshot is None:
            return
        try:
            snapshot = await self._budget_snapshot()
            data["budget_spent_today_usd"] = float(snapshot.spent_today_usd)
            data["budget_remaining_month_usd"] = float(snapshot.remaining_month_usd)
        except Exception:
            unavailable.append("budjet")


async def build_world_state_text(builder: WorldStateBuilder) -> str:
    """`WorldStateBuilder` → prompt bloki (to'liq fail-open).

    Qurish yiqilsa BO'SH matn qaytadi — kontekst bloki majburiy emas,
    uning yo'qligi run'ni to'xtatmasligi kerak.
    """
    try:
        state = await builder.build()
    except Exception:
        log.warning("world_state.build_failed")
        return ""
    return state.to_prompt_block()


__all__ = ["WorldState", "WorldStateBuilder", "build_world_state_text"]
