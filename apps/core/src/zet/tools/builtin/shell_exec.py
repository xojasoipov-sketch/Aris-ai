"""shell.exec — cheklangan shell buyruqlari (Z1.10).

Ruxsat: EXECUTE — eng xavfli daraja.
Trust: SYSTEM — lekin buyruq chiqishi UNTRUSTED bo'lishi mumkin.
Idempotent: yo'q.

🔴 ENG XAVFLI KOMPONENT. Yumshatish choralari:
    1. Default OFF (`ZET_ENABLE_SHELL=false`)
    2. Qattiq allowlist — faqat ruxsat berilgan buyruqlar
    3. Argument sanitizatsiyasi — shell injection oldini olish
    4. Timeout — 30s default
    5. Majburiy approval (EXECUTE daraja → approval gate)
    6. Audit — har bir chaqiruv tool_call jadvaliga yoziladi

Bog'liq qarorlar:
    V-31 — EXECUTE ruxsat darajasi
    V-32 — majburiy approval
    A-07 — timeout chegarasi
"""

from __future__ import annotations

import asyncio
import shlex
from typing import Any

from zet.domain.enums import PermissionLevel, TrustLevel
from zet.tools.base import Tool, ToolError

# Ruxsat berilgan buyruqlar — faqat xavfsiz, o'qish tipidagi buyruqlar
_DEFAULT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "date",
        "whoami",
        "hostname",
        "uptime",
        "uname",
        "df",
        "free",
        "ls",
        "cat",
        "head",
        "tail",
        "wc",
        "echo",
        "pwd",
        "which",
        "env",
        "printenv",
    }
)

# Shell meta-belgilar — injection oldini olish
_DANGEROUS_CHARS = frozenset(";|&$`(){}[]!><#")


class ShellExecTool(Tool):
    """Cheklangan shell buyruqlarini bajaradi.

    Faqat allowlist'dagi buyruqlar bajariladi.
    Default holatda O'CHIRILGAN — `ZET_ENABLE_SHELL=true` kerak.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        allowlist: frozenset[str] | None = None,
        timeout_override: int = 30,
    ) -> None:
        self._enabled = enabled
        self._allowlist = allowlist if allowlist is not None else _DEFAULT_ALLOWLIST
        self._timeout = timeout_override

    @property
    def name(self) -> str:
        return "shell.exec"

    @property
    def description(self) -> str:
        return (
            "Cheklangan shell buyruqlarini bajaradi "
            "(faqat allowlist'dagi buyruqlar, approval kerak)"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "Bajariladigan buyruq "
                        f"(ruxsat berilganlar: {', '.join(sorted(self._allowlist))})"
                    ),
                    "minLength": 1,
                    "maxLength": 1024,
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.EXECUTE

    @property
    def output_trust_level(self) -> TrustLevel:
        return TrustLevel.UNTRUSTED

    @property
    def idempotent(self) -> bool:
        return False

    @property
    def timeout_s(self) -> int:
        return self._timeout

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._enabled:
            raise ToolError("shell.exec o'chirilgan. Yoqish uchun: ZET_ENABLE_SHELL=true (xavfli!)")

        raw_command: str = params["command"]

        # Shell meta-belgilarni tekshirish (injection oldini olish)
        for char in raw_command:
            if char in _DANGEROUS_CHARS:
                raise ToolError(
                    f"Xavfli belgi '{char}' topildi. "
                    "Shell operatorlari (;|&$`va boshqalar) ruxsat berilmagan."
                )

        # Buyruqni ajratish
        try:
            parts = shlex.split(raw_command)
        except ValueError as exc:
            raise ToolError(f"Buyruq tahlil qilib bo'lmadi: {exc}") from exc

        if not parts:
            raise ToolError("Bo'sh buyruq")

        # Allowlist tekshiruvi
        cmd_name = parts[0]
        if cmd_name not in self._allowlist:
            raise ToolError(
                f"Buyruq '{cmd_name}' ruxsat berilmagan. "
                f"Ruxsat berilganlar: {', '.join(sorted(self._allowlist))}"
            )

        # Bajarish
        try:
            proc = await asyncio.create_subprocess_exec(
                *parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._timeout,
            )
        except TimeoutError as exc:
            raise ToolError(f"Buyruq {self._timeout}s ichida yakunlanmadi") from exc
        except OSError as exc:
            raise ToolError(f"Buyruq bajarib bo'lmadi: {exc}") from exc

        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

        return {
            "command": raw_command,
            "exit_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "success": proc.returncode == 0,
        }
