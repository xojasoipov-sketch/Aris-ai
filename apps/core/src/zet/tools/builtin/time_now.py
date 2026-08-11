"""time.now — hozirgi vaqt va sana (Z1.10).

Ruxsat: READ — faqat o'qish, hech narsa o'zgartirmaydi.
Trust: SYSTEM — ichki tool.
Idempotent: yo'q (har safar yangi vaqt).

Bog'liq qarorlar:
    V-31 — READ ruxsat darajasi
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from zet.domain.enums import PermissionLevel
from zet.tools.base import Tool


class TimeNowTool(Tool):
    """Hozirgi vaqt va sanani qaytaradi."""

    def __init__(self, *, default_tz: str = "Asia/Tashkent") -> None:
        self._default_tz = default_tz

    @property
    def name(self) -> str:
        return "time.now"

    @property
    def description(self) -> str:
        return "Hozirgi vaqt va sanani ko'rsatadi (vaqt mintaqasi bilan)"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "IANA vaqt mintaqasi (masalan: Asia/Tashkent, UTC)",
                    "default": self._default_tz,
                },
            },
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    @property
    def idempotent(self) -> bool:
        return False

    @property
    def timeout_s(self) -> int:
        return 5

    async def _execute(self, params: dict[str, Any]) -> dict[str, str]:
        tz_name = params.get("timezone", self._default_tz)
        tz = ZoneInfo(tz_name)
        now = datetime.now(tz=tz)
        return {
            "datetime": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "timezone": tz_name,
            "weekday": now.strftime("%A"),
            "unix_timestamp": str(int(now.timestamp())),
        }
