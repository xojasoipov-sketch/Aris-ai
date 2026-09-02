"""Z1.10 — Tool bazaviy sinfi va Registry testlari.

Tekshiriladi:
    - Tool.execute() muvaffaqiyatli natija qaytaradi
    - Tool.execute() xatoni ushlaydi va ToolResult qaytaradi
    - Tool.execute() timeout da ToolResult(success=False) qaytaradi
    - dry_run=True da haqiqiy ish bajarilmaydi
    - Registry: ro'yxatga olish, topish, execute
    - Registry: mavjud bo'lmagan tool → ToolNotFoundError
    - Registry: JSON Schema validatsiyasi
    - Registry: permission tekshiruvi
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from zet.domain.enums import PermissionLevel, TrustLevel
from zet.tools.base import Tool, ToolError, ToolPermissionDeniedError, ToolValidationError
from zet.tools.registry import ToolNotFoundError, ToolRegistry


class _EchoTool(Tool):
    """Test uchun oddiy tool — kirishni qaytaradi."""

    @property
    def name(self) -> str:
        return "test.echo"

    @property
    def description(self) -> str:
        return "Kirishni qaytaradi"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
            },
            "required": ["message"],
            "additionalProperties": False,
        }

    async def _execute(self, params: dict[str, Any]) -> dict[str, str]:
        return {"echo": params["message"]}


class _FailTool(Tool):
    """Test uchun — har doim xato beradi."""

    @property
    def name(self) -> str:
        return "test.fail"

    @property
    def description(self) -> str:
        return "Har doim xato beradi"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def _execute(self, params: dict[str, Any]) -> Any:
        raise ToolError("Qasddan xato")


class _SlowTool(Tool):
    """Test uchun — uzoq vaqt ishlaydi."""

    @property
    def name(self) -> str:
        return "test.slow"

    @property
    def description(self) -> str:
        return "Uzoq ishlaydi"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    @property
    def timeout_s(self) -> int:
        return 1

    async def _execute(self, params: dict[str, Any]) -> None:
        await asyncio.sleep(10)


class _WriteTool(Tool):
    """Test uchun — WRITE ruxsat talab qiladi."""

    @property
    def name(self) -> str:
        return "test.write"

    @property
    def description(self) -> str:
        return "WRITE ruxsat kerak"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.WRITE

    async def _execute(self, params: dict[str, Any]) -> str:
        return "yozildi"


class _CrashTool(Tool):
    """Test uchun — kutilmagan xato (Exception)."""

    @property
    def name(self) -> str:
        return "test.crash"

    @property
    def description(self) -> str:
        return "Kutilmagan xato beradi"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def _execute(self, params: dict[str, Any]) -> Any:
        raise RuntimeError("Kutilmagan")


class TestToolExecute:
    """Tool.execute() testlari."""

    async def test_success(self) -> None:
        """Muvaffaqiyatli natija."""
        tool = _EchoTool()
        result = await tool.execute({"message": "salom"})

        assert result.success is True
        assert result.output == {"echo": "salom"}
        assert result.tool_name == "test.echo"
        assert result.trust_level == TrustLevel.SYSTEM
        assert result.latency_ms >= 0
        assert result.error is None

    async def test_tool_error(self) -> None:
        """ToolError — success=False, xato xabari bor."""
        tool = _FailTool()
        result = await tool.execute({})

        assert result.success is False
        assert result.error == "Qasddan xato"
        assert result.tool_name == "test.fail"

    async def test_timeout(self) -> None:
        """Timeout — success=False."""
        tool = _SlowTool()
        result = await tool.execute({})

        assert result.success is False
        assert "yakunlanmadi" in (result.error or "")

    async def test_unexpected_error(self) -> None:
        """Kutilmagan xato — success=False, xato turi ko'rsatiladi."""
        tool = _CrashTool()
        result = await tool.execute({})

        assert result.success is False
        assert "RuntimeError" in (result.error or "")

    async def test_dry_run(self) -> None:
        """dry_run=True — haqiqiy bajarilmaydi."""
        tool = _EchoTool()
        result = await tool.execute({"message": "test"}, dry_run=True)

        assert result.success is True
        assert result.output["dry_run"] is True
        assert result.output["would_execute"] == "test.echo"

    async def test_properties(self) -> None:
        """Tool xususiyatlari to'g'ri."""
        tool = _EchoTool()
        assert tool.name == "test.echo"
        assert tool.permission_level == PermissionLevel.READ
        assert tool.output_trust_level == TrustLevel.SYSTEM
        assert tool.idempotent is True
        assert tool.timeout_s == 30


class TestToolRegistry:
    """ToolRegistry testlari."""

    def test_register_and_get(self) -> None:
        """Tool ro'yxatga olinadi va topiladi."""
        registry = ToolRegistry()
        registry.register(_EchoTool())

        tool = registry.get("test.echo")
        assert tool.name == "test.echo"
        assert registry.has("test.echo")
        assert not registry.has("nonexistent")

    def test_register_duplicate_raises(self) -> None:
        """Ikki marta ro'yxatga olish → ValueError."""
        registry = ToolRegistry()
        registry.register(_EchoTool())

        with pytest.raises(ValueError, match="allaqachon"):
            registry.register(_EchoTool())

    def test_get_not_found(self) -> None:
        """Mavjud bo'lmagan tool → ToolNotFoundError."""
        registry = ToolRegistry()

        with pytest.raises(ToolNotFoundError, match="topilmadi"):
            registry.get("nonexistent")

    def test_list_tools(self) -> None:
        """list_tools barcha toollarni qaytaradi."""
        registry = ToolRegistry()
        registry.register(_EchoTool())
        registry.register(_FailTool())

        tools = registry.list_tools()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"test.echo", "test.fail"}

    def test_tool_names(self) -> None:
        """tool_names faqat nomlarni qaytaradi."""
        registry = ToolRegistry()
        registry.register(_EchoTool())

        assert registry.tool_names() == ["test.echo"]

    def test_validate_input_valid(self) -> None:
        """To'g'ri input — bo'sh xatolar."""
        registry = ToolRegistry()
        registry.register(_EchoTool())

        errors = registry.validate_input("test.echo", {"message": "salom"})
        assert errors == []

    def test_validate_input_invalid(self) -> None:
        """Noto'g'ri input — xatolar bor."""
        registry = ToolRegistry()
        registry.register(_EchoTool())

        errors = registry.validate_input("test.echo", {"message": 123})
        assert len(errors) > 0

    def test_validate_input_missing_required(self) -> None:
        """Majburiy parametr yo'q."""
        registry = ToolRegistry()
        registry.register(_EchoTool())

        errors = registry.validate_input("test.echo", {})
        assert len(errors) > 0

    async def test_execute_success(self) -> None:
        """Registry orqali muvaffaqiyatli bajarish."""
        registry = ToolRegistry()
        registry.register(_EchoTool())

        result = await registry.execute("test.echo", {"message": "salom"})
        assert result.success is True
        assert result.output == {"echo": "salom"}

    async def test_execute_not_found(self) -> None:
        """Mavjud bo'lmagan tool → ToolNotFoundError."""
        registry = ToolRegistry()

        with pytest.raises(ToolNotFoundError):
            await registry.execute("nonexistent", {})

    async def test_execute_validation_error(self) -> None:
        """Noto'g'ri input → ToolValidationError."""
        registry = ToolRegistry()
        registry.register(_EchoTool())

        with pytest.raises(ToolValidationError, match="noto'g'ri parametrlar"):
            await registry.execute("test.echo", {"message": 123})

    async def test_execute_permission_denied(self) -> None:
        """Yetarli ruxsat yo'q → ToolPermissionDeniedError."""
        registry = ToolRegistry()
        registry.register(_WriteTool())

        with pytest.raises(ToolPermissionDeniedError, match="ruxsat kerak"):
            await registry.execute(
                "test.write",
                {},
                caller_permission=PermissionLevel.READ,
            )

    async def test_execute_permission_sufficient(self) -> None:
        """Yetarli ruxsat → muvaffaqiyatli."""
        registry = ToolRegistry()
        registry.register(_WriteTool())

        result = await registry.execute(
            "test.write",
            {},
            caller_permission=PermissionLevel.WRITE,
        )
        assert result.success is True

    async def test_execute_higher_permission_ok(self) -> None:
        """Yuqori ruxsat ham yetarli."""
        registry = ToolRegistry()
        registry.register(_WriteTool())

        result = await registry.execute(
            "test.write",
            {},
            caller_permission=PermissionLevel.EXECUTE,
        )
        assert result.success is True

    async def test_execute_dry_run(self) -> None:
        """dry_run registry orqali ishlaydi."""
        registry = ToolRegistry()
        registry.register(_EchoTool())

        result = await registry.execute(
            "test.echo",
            {"message": "test"},
            dry_run=True,
        )
        assert result.success is True
        assert result.output["dry_run"] is True
