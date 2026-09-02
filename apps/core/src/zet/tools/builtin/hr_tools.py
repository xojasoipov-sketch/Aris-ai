"""HR agent tool'lari — AI workforce management (yangi asosiy talab).

HR agent ilgari inson-HR tahlilchisi edi (`web.search`+`web.read` bilan).
Endi u ZET ekotizimidagi BOSHQA AI agentlarni boshqaradi:
    - agent ro'yxati va holati (`agent.list`)
    - vaqtincha to'xtatish (`agent.pause`)
    - qayta yoqish (`agent.resume`)
    - o'chirib qo'yish (`agent.disable`)
    - metrikalarini ko'rish (`agent.stats`)

Xavfsizlik: agent factory (yangi agent yaratish) BU YERDA YO'Q — u
alohida `AgentFactory` API'si orqali va odam tasdig'i talab qiladi.
Bu tool'lar faqat MAVJUD agentlarni boshqaradi. Har harakat EXECUTE
darajada — ega tasdig'ini kutmaydi (chunki agentlar orasidagi harakat),
lekin `PermissionPolicy` HR agent'ining o'z darajasini tekshiradi.

Bog'liq qarorlar:
    V-11 — lifecycle: DRAFT→TESTING→ACTIVE→PAUSED→DISABLED→ARCHIVED
    A-02 — Agent = ma'lumot (yozuv), kod emas
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from zet.domain.enums import AgentStatus, PermissionLevel
from zet.tools.base import Tool, ToolError

if TYPE_CHECKING:
    from zet.agents.registry import AgentRegistry


class _RegistryTool(Tool):
    """Agent registry'ni ishlatuvchi tool'lar uchun umumiy asos."""

    def __init__(self, *, registry: AgentRegistry | None = None) -> None:
        self._registry = registry

    @property
    def connected(self) -> bool:
        return self._registry is not None

    def _require_registry(self) -> AgentRegistry:
        if self._registry is None:
            raise ToolError("Agent registry ulanmagan — HR tool'lari ishlamaydi")
        return self._registry


class AgentListTool(_RegistryTool):
    """Barcha agentlar ro'yxati (holati, mas'uliyati)."""

    @property
    def name(self) -> str:
        return "agent.list"

    @property
    def description(self) -> str:
        return "ZET ekotizimidagi agentlar ro'yxati (holati, mas'uliyati, metrikalari)."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["draft", "testing", "active", "paused", "disabled", "archived"],
                    "description": "Faqat shu holatdagi agentlar (ixtiyoriy).",
                }
            },
            "additionalProperties": False,
        }

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        registry = self._require_registry()
        status_str = params.get("status")
        status = AgentStatus(status_str) if status_str else None
        agents = registry.list_agents(status=status)
        return {"agents": [_agent_dict(a) for a in agents]}


class AgentPauseTool(_RegistryTool):
    """Agentni ACTIVE→PAUSED holatiga o'tkazish."""

    @property
    def name(self) -> str:
        return "agent.pause"

    @property
    def description(self) -> str:
        return "Agentni vaqtincha to'xtatish (ACTIVE→PAUSED). Ish tugagach `agent.resume`."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"name": {"type": "string", "minLength": 1}},
            "required": ["name"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.EXECUTE

    @property
    def idempotent(self) -> bool:
        return False

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        registry = self._require_registry()
        try:
            state = registry.update_status(params["name"], AgentStatus.PAUSED)
        except ValueError as exc:
            raise ToolError(f"O'tishga ruxsat yo'q: {exc}") from exc
        return {"agent": _agent_dict(state)}


class AgentResumeTool(_RegistryTool):
    """Agentni PAUSED→ACTIVE holatiga qaytarish."""

    @property
    def name(self) -> str:
        return "agent.resume"

    @property
    def description(self) -> str:
        return "To'xtatilgan yoki testdagi agentni ACTIVE holatiga o'tkazish."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"name": {"type": "string", "minLength": 1}},
            "required": ["name"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.EXECUTE

    @property
    def idempotent(self) -> bool:
        return False

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        registry = self._require_registry()
        try:
            state = registry.update_status(params["name"], AgentStatus.ACTIVE)
        except ValueError as exc:
            raise ToolError(f"O'tishga ruxsat yo'q: {exc}") from exc
        return {"agent": _agent_dict(state)}


class AgentDisableTool(_RegistryTool):
    """Agentni butunlay o'chirib qo'yish (DISABLED)."""

    @property
    def name(self) -> str:
        return "agent.disable"

    @property
    def description(self) -> str:
        return "Agentni butunlay o'chirib qo'yish (DISABLED). `agent.resume` bilan yoqilmaydi."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"name": {"type": "string", "minLength": 1}},
            "required": ["name"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.EXECUTE

    @property
    def idempotent(self) -> bool:
        return False

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        registry = self._require_registry()
        try:
            state = registry.update_status(params["name"], AgentStatus.DISABLED)
        except ValueError as exc:
            raise ToolError(f"O'tishga ruxsat yo'q: {exc}") from exc
        return {"agent": _agent_dict(state)}


class AgentStatsTool(_RegistryTool):
    """Bitta agentning metrikalari (jami/muvaffaqiyatli run soni, oxirgi ishlagan vaqt)."""

    @property
    def name(self) -> str:
        return "agent.stats"

    @property
    def description(self) -> str:
        return "Bitta agent metrikalari — jami runs, success_rate, oxirgi ish vaqti."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"name": {"type": "string", "minLength": 1}},
            "required": ["name"],
            "additionalProperties": False,
        }

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        registry = self._require_registry()
        try:
            state = registry.get(params["name"])
        except Exception as exc:
            raise ToolError(f"Agent topilmadi: {exc}") from exc
        total = state.total_runs
        ok = state.successful_runs
        rate = (ok / total) if total else None
        return {
            "name": state.spec.name,
            "status": state.status.value,
            "total_runs": total,
            "successful_runs": ok,
            "success_rate": rate,
        }


def _agent_dict(state: object) -> dict[str, Any]:
    return {
        "name": state.spec.name,  # type: ignore[attr-defined]
        "role": state.spec.role,  # type: ignore[attr-defined]
        "division": state.spec.division,  # type: ignore[attr-defined]
        "status": state.status.value,  # type: ignore[attr-defined]
        "permission": state.spec.permission_level.value,  # type: ignore[attr-defined]
        "tool_count": len(state.spec.tool_allowlist),  # type: ignore[attr-defined]
        "total_runs": state.total_runs,  # type: ignore[attr-defined]
        "successful_runs": state.successful_runs,  # type: ignore[attr-defined]
    }


__all__ = [
    "AgentDisableTool",
    "AgentListTool",
    "AgentPauseTool",
    "AgentResumeTool",
    "AgentStatsTool",
]
