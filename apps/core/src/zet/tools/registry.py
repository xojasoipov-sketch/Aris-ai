"""Tool Registry — toollarni ro'yxatga olish va topish (Z1.10).

Barcha toollar Registry orqali ishga tushadi — bu allowlist,
validatsiya va audit uchun yagona nuqta.

Bog'liq qarorlar:
    V-31 — permission tekshiruvi
    A-07 — timeout, rate limit chegaralari
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import jsonschema
import structlog

from zet.domain.enums import PermissionLevel
from zet.domain.tool import ToolResult
from zet.tools.base import Tool, ToolPermissionDeniedError, ToolValidationError

log = structlog.get_logger(__name__)


class ToolNotFoundError(Exception):
    """Registry'da bunday tool yo'q."""


class ToolRegistry:
    """Tool'larni ro'yxatga olish, topish va xavfsiz bajarish.

    - Faqat ro'yxatga olingan toollar ishlaydi (allowlist prinsipi)
    - JSON Schema validatsiyasi execute() oldidan amalga oshiriladi
    - Permission tekshiruvi — caller ruxsati yetarli bo'lishi kerak
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Tool'ni ro'yxatga oladi.

        Args:
            tool: ro'yxatga olinadigan tool

        Raises:
            ValueError: agar shu nomda tool allaqachon ro'yxatda bo'lsa
        """
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' allaqachon ro'yxatda")
        self._tools[tool.name] = tool
        log.info("registry.registered", tool=tool.name, permission=tool.permission_level.value)

    def get(self, name: str) -> Tool:
        """Nom bo'yicha tool'ni topadi.

        Raises:
            ToolNotFoundError: registry'da yo'q
        """
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"Tool '{name}' registry'da topilmadi") from exc

    def list_tools(self) -> Sequence[Tool]:
        """Barcha ro'yxatdagi toollar."""
        return list(self._tools.values())

    def tool_names(self) -> list[str]:
        """Barcha ro'yxatdagi tool nomlari."""
        return list(self._tools.keys())

    def has(self, name: str) -> bool:
        """Tool mavjudligini tekshiradi."""
        return name in self._tools

    def validate_input(self, tool_name: str, params: dict[str, Any]) -> list[str]:
        """Input'ni tool'ning JSON Schema'siga tekshiradi.

        Returns:
            Xatolar ro'yxati (bo'sh = validatsiya muvaffaqiyatli)
        """
        tool = self.get(tool_name)
        errors: list[str] = []
        try:
            jsonschema.validate(instance=params, schema=tool.input_schema)
        except jsonschema.ValidationError as exc:
            errors.append(str(exc.message))
        return errors

    async def execute(
        self,
        tool_name: str,
        params: dict[str, Any],
        *,
        caller_permission: PermissionLevel = PermissionLevel.READ,
        dry_run: bool = False,
    ) -> ToolResult:
        """Tool'ni xavfsiz bajaradi: allowlist + validatsiya + permission + execute.

        Args:
            tool_name: tool nomi
            params: kirish parametrlari
            caller_permission: chaqiruvchining ruxsat darajasi
            dry_run: haqiqiy ish bajarmaslik

        Returns:
            ToolResult

        Raises:
            ToolNotFoundError: registry'da yo'q
            ToolValidationError: input schema'ga mos kelmadi
            ToolPermissionDeniedError: ruxsat yetarli emas
        """
        tool = self.get(tool_name)

        # Permission tekshiruvi (V-31)
        if caller_permission < tool.permission_level:
            raise ToolPermissionDeniedError(
                f"Tool '{tool_name}' uchun {tool.permission_level.value} "
                f"ruxsat kerak, lekin {caller_permission.value} berilgan"
            )

        # JSON Schema validatsiyasi
        validation_errors = self.validate_input(tool_name, params)
        if validation_errors:
            raise ToolValidationError(
                f"Tool '{tool_name}' uchun noto'g'ri parametrlar: " + "; ".join(validation_errors)
            )

        # Bajarish
        log.info(
            "registry.execute",
            tool=tool_name,
            dry_run=dry_run,
            permission=caller_permission.value,
        )
        return await tool.execute(params, dry_run=dry_run)
