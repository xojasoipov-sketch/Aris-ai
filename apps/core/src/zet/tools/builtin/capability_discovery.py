"""system.capabilities — "nima qila olasiz?" savoliga HAQIQIY javob (JB-16).

NEGA. Real ishlab chiqarish nosozligi (JB-16 CASE A): ega Telegram'da
"Biz nimalar qilolamiz bu kanal uchun qanday toolarimiz bor" deb
so'raganda, hech qanday kod yo'li REGISTRY'ni tekshirmasdi — LLM
faqat o'z bilimidan ("thinking" qadam) javob TO'QIRDI, mumkin bo'lgan
tool ro'yxati bilan HAQIQIY mos kelish-kelmasligidan qat'i nazar.

Bu tool — muammoni "capability discovery"ni Brain/Mission darajasida
ALOHIDA yo'l sifatida qo'shish O'RNIGA (bu ikkinchi bir arxitektura
qatlami bo'lardi), oddiy TOOL sifatida taqdim etadi: Planner uni boshqa
har qanday tool kabi semantik ravishda tanlaydi ("nima qila olasiz"
so'raganda), u esa HAQIQIY `ToolRegistry`dan (o'ylab topilgan emas)
har bir tool holatini o'qiydi:

    - AVAILABLE — tool ishlaydi (kalit/token sozlangan yoki lokal)
    - NOT_AVAILABLE — tool stub rejimida (kalit/token yo'q)
    - REQUIRES_PERMISSION — READ'dan yuqori ruxsat talab qiladi
    - REQUIRES_APPROVAL — xavf darajasi ega tasdig'ini talab qiladi

`topic` (ixtiyoriy) — natijani bitta so'z bilan filtrlaydi (masalan
"telegram", "kanal"), CapabilityRegistry.search()dagi bilan bir xil
oddiy pastki-satr qidiruvi — YANGI kalit so'zlar ro'yxati EMAS.

Xavfsizlik: permission=READ, risk=LOW (default) — hech narsani
o'zgartirmaydi, faqat registry holatini o'qiydi.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from zet.domain.enums import PermissionLevel, TrustLevel
from zet.security.permissions import PermissionPolicy
from zet.tools.base import Tool

if TYPE_CHECKING:
    from zet.tools.registry import ToolRegistry


def _tool_status(tool: Any, policy: PermissionPolicy) -> dict[str, Any]:
    """Bitta tool uchun haqiqiy holat — registry'dan, taxmin emas."""
    is_real = getattr(tool, "is_real", True)  # lokal tool'larda bu maydon yo'q — doim mavjud
    decision = policy.requires_approval(
        permission=tool.permission_level,
        trust=TrustLevel.OWNER,
        tool=tool,
    )
    return {
        "name": tool.name,
        "description": tool.description,
        "permission": tool.permission_level.value,
        "risk": tool.risk_level.value,
        "available": bool(is_real),
        "requires_permission": tool.permission_level != PermissionLevel.READ,
        "requires_approval": decision.needs_approval,
    }


class CapabilityDiscoveryTool(Tool):
    """`ToolRegistry`dan HAQIQIY tool ro'yxati va holatini qaytaradi."""

    def __init__(self, *, registry: ToolRegistry | None = None) -> None:
        # `registry` — `build_default_registry()` ICHIDA, o'ziga
        # ro'yxatga olinishidan OLDIN yaratilgan bo'sh `ToolRegistry`
        # obyektiga ISHORA (keyinroq boshqa `register()` chaqiruvlari
        # bilan to'ldiriladi). `_execute()` bu ishorani so'rov VAQTIDA
        # o'qiydi — konstruksiya vaqtida emas — shuning uchun bo'sh
        # bo'lish muammosi yo'q (Python ob'ekt REFERENCE, nusxa emas).
        self._registry = registry
        self._policy = PermissionPolicy()

    @property
    def name(self) -> str:
        return "system.capabilities"

    @property
    def description(self) -> str:
        return (
            "ZET nima qila olishini so'raganda ('nima qila olasiz', "
            "'qanday toolaringiz bor', 'bu uchun nima ishlata olasiz') "
            "shu tool'ni ishlating — o'ylab topilgan emas, HAQIQIY "
            "registry holatidan (mavjud/mavjud emas/ruxsat/tasdiq kerak) "
            "javob qaytaradi."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": (
                        "Ixtiyoriy: natijani bitta mavzu so'zi bilan toraytirish "
                        "(masalan 'telegram', 'kanal'). Bo'sh — barcha tool'lar."
                    ),
                },
            },
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    @property
    def idempotent(self) -> bool:
        return True

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        if self._registry is None:
            return {
                "total": 0,
                "available": [],
                "not_available": [],
                "requires_approval": [],
                "summary_text": "Tool registry ulanmagan — ro'yxat topilmadi.",
            }

        topic = str(params.get("topic") or "").strip().lower()
        tools = list(self._registry.list_tools())
        if topic:
            tools = [
                t
                for t in tools
                if topic in t.name.lower() or topic in t.description.lower()
            ]

        statuses = [_tool_status(t, self._policy) for t in tools]
        available = [s for s in statuses if s["available"]]
        not_available = [s for s in statuses if not s["available"]]
        requires_approval = [s for s in statuses if s["requires_approval"]]

        lines: list[str] = []
        if not statuses:
            lines.append(
                f"'{topic}' mavzusi bo'yicha hech qanday tool topilmadi."
                if topic
                else "Registry'da hech qanday tool yo'q."
            )
        else:
            lines.append(f"Jami {len(statuses)} ta tool topildi:")
            for s in available:
                approval_note = " (ega tasdig'i kerak)" if s["requires_approval"] else ""
                lines.append(f"- {s['name']}: {s['description']}{approval_note}")
            if not_available:
                names = ", ".join(s["name"] for s in not_available)
                lines.append(
                    f"Sozlanmagan (kalit/token yo'q, hozircha ishlamaydi): {names}"
                )

        return {
            "total": len(statuses),
            "available": available,
            "not_available": not_available,
            "requires_approval": requires_approval,
            "summary_text": "\n".join(lines),
        }


__all__ = ["CapabilityDiscoveryTool"]
