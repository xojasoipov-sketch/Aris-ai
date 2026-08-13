"""Tool bazaviy interfeysi (Z1.10).

Har bir tool shu interfeys orqali ishlaydi — Registry va Executor shunga tayanadi.

Bog'liq qarorlar:
    A-05 — har bir tool natijasida trust level bor
    V-31 — har bir toolda permission darajasi
    A-07 — timeout, dry_run chegaralari
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any

import structlog

from zet.domain.enums import PermissionLevel, RiskLevel, TrustLevel
from zet.domain.tool import ToolResult
from zet.security.risk import risk_for

log = structlog.get_logger(__name__)


class ToolError(Exception):
    """Tool bajarilishida umumiy xato."""


class ToolQuotaError(ToolError):
    """Tashqi xizmat kvotasi/limiti tugadi.

    Darhol qayta urinish yordam bermaydi — Executor bu xatoni
    takrorlamaydi."""


class ToolTimeoutError(ToolError):
    """Tool belgilangan vaqt ichida yakunlanmadi (A-07)."""


class ToolPermissionDeniedError(ToolError):
    """Tool uchun yetarli ruxsat yo'q (V-31)."""


class ToolValidationError(ToolError):
    """Kirish JSON Schema'ga mos kelmadi."""


class Tool(ABC):
    """Tool bazaviy sinfi.

    Har bir tool shu sinfni nasllab olishi kerak:
    - `name`: unikal tool nomi (masalan: "time.now")
    - `description`: qisqa tavsif
    - `input_schema`: JSON Schema (parametrlar uchun)
    - `permission_level`: kerakli ruxsat darajasi (V-31)
    - `output_trust_level`: natija ishonch darajasi (A-05)
    - `idempotent`: qayta chaqirilsa xavfsizmi
    - `timeout_s`: maksimal bajarilish vaqti
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unikal tool nomi."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Qisqa tavsif (LLM uchun)."""

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema — tool parametrlarini validatsiya qilish uchun."""

    @property
    def permission_level(self) -> PermissionLevel:
        """Kerakli ruxsat darajasi. Default: READ."""
        return PermissionLevel.READ

    @property
    def risk_level(self) -> RiskLevel:
        """Xavf darajasi — ega tasdig'i kerakmi (V-32 kengaytmasi).

        Default: markazlashtirilgan `TOOL_RISK_LEVELS` jadvalidan
        qidiriladi; topilmasa `RiskLevel.LOW`. Har bir subclass
        bir qatorli property bilan override qilishi mumkin — jadvaldagi
        yozuvni bosadi (jadval faqat bo'shliqni to'ldiradi).

        NEGA property jadvaldan yuqori emas: eski subclass'lar
        `risk_level`ni umuman bilmasdi va default LOW olardi. Endi ular
        avtomatik jadvaldan tortadi va faqat "men aniq boshqacha
        beraman" degan subclass override qilib bosadi. Bu — foydali
        va xavfsiz fallback.

        Ilgari HIGH_RISK_TOOLS frozenset faqat "yuqori xavflimi?"
        bool qaytarardi; MEDIUM'ni bermas edi va business writes bir
        tanlovsiz avtomatik ketardi.
        """
        return risk_for(self.name)

    @property
    def output_trust_level(self) -> TrustLevel:
        """Natija ishonch darajasi. Default: SYSTEM."""
        return TrustLevel.SYSTEM

    @property
    def idempotent(self) -> bool:
        """Qayta chaqirilsa xavfsiz. Default: True."""
        return True

    @property
    def timeout_s(self) -> int:
        """Maksimal bajarilish vaqti (sekundda). Default: 30."""
        return 30

    @abstractmethod
    async def _execute(self, params: dict[str, Any]) -> Any:
        """Tool mantiqiy bajarilishi (subclass tomonidan amalga oshiriladi).

        Args:
            params: validatsiya qilingan parametrlar

        Returns:
            Natija qiymati (JSON-serializatsiya qilinadigan)

        Raises:
            ToolError: bajarilishda xato
        """

    async def execute(
        self,
        params: dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> ToolResult:
        """Toolni bajaradi — validatsiya, timeout, dry_run bilan.

        Args:
            params: kirish parametrlari
            dry_run: True bo'lsa, haqiqiy ish bajarilmaydi

        Returns:
            ToolResult — muvaffaqiyat yoki xato bilan
        """
        start_ms = _now_ms()

        if dry_run:
            log.info("tool.dry_run", tool=self.name, params=params)
            return ToolResult(
                tool_name=self.name,
                success=True,
                output={"dry_run": True, "would_execute": self.name, "params": params},
                trust_level=self.output_trust_level,
                latency_ms=_now_ms() - start_ms,
            )

        try:
            result = await asyncio.wait_for(
                self._execute(params),
                timeout=self.timeout_s,
            )
        except TimeoutError:
            latency = _now_ms() - start_ms
            log.warning("tool.timeout", tool=self.name, timeout_s=self.timeout_s)
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Tool {self.timeout_s}s ichida yakunlanmadi",
                trust_level=self.output_trust_level,
                latency_ms=latency,
            )
        except ToolError as exc:
            latency = _now_ms() - start_ms
            retryable = not isinstance(exc, ToolQuotaError)
            log.warning("tool.error", tool=self.name, error=str(exc), retryable=retryable)
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
                trust_level=self.output_trust_level,
                latency_ms=latency,
                retryable=retryable,
            )
        except Exception as exc:
            latency = _now_ms() - start_ms
            log.exception("tool.unexpected_error", tool=self.name)
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Kutilmagan xato: {type(exc).__name__}: {exc}",
                trust_level=self.output_trust_level,
                latency_ms=latency,
            )
        else:
            latency = _now_ms() - start_ms
            log.info("tool.ok", tool=self.name, latency_ms=latency)
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=result,
                trust_level=self.output_trust_level,
                latency_ms=latency,
            )


def _now_ms() -> int:
    """Millisekundlarda hozirgi vaqt (monotonic)."""
    return int(time.monotonic() * 1000)
