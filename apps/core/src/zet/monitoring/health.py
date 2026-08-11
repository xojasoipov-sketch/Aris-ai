"""Health Checker — tizim salomatligi (Bo'lim 10).

Har bir tizim komponentini tekshiradi va umumiy holat beradi.

Komponentlar:
    - database — DB ulanishi
    - llm — LLM provayder javob berishi
    - budget — budjet holati
    - scheduler — jadvallar holati
    - killswitch — kill switch holati

Bog'liq qarorlar:
    Bo'lim 10 — monitoring
    A-07 — tormozlar
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)


class ComponentStatus(StrEnum):
    """Komponent holati."""

    HEALTHY = "healthy"
    """Normal ishlayapti."""

    DEGRADED = "degraded"
    """Ishlayapti, lekin muammolar bor."""

    UNHEALTHY = "unhealthy"
    """Ishlamayapti."""

    UNKNOWN = "unknown"
    """Holati noma'lum."""


class ComponentHealth(BaseModel, frozen=True):
    """Bitta komponent salomatligi."""

    name: str
    """Komponent nomi."""

    status: ComponentStatus
    """Holat."""

    message: str = ""
    """Qo'shimcha ma'lumot."""

    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Tekshirilgan vaqt."""

    response_ms: float = 0.0
    """Javob vaqti (millisekundda)."""


class HealthReport(BaseModel, frozen=True):
    """Umumiy salomatlik hisoboti."""

    status: ComponentStatus
    """Umumiy holat (eng yomon komponent holati)."""

    components: list[ComponentHealth] = Field(default_factory=list)
    """Komponentlar holati."""

    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Hisobot vaqti."""

    @property
    def is_healthy(self) -> bool:
        """Tizim sog'lommi."""
        return self.status == ComponentStatus.HEALTHY

    @property
    def unhealthy_components(self) -> list[ComponentHealth]:
        """Nosog'lom komponentlar."""
        return [c for c in self.components if c.status != ComponentStatus.HEALTHY]


class HealthChecker:
    """Tizim salomatligini tekshirish.

    Har bir komponent uchun callback funksiya ro'yxatga olinadi.
    check_all() barcha komponentlarni tekshiradi va hisobot beradi.
    """

    def __init__(self) -> None:
        self._checks: dict[str, _HealthCheckFn] = {}

    def register(self, name: str, check_fn: _HealthCheckFn) -> None:
        """Komponent tekshiruvini ro'yxatga olish.

        Args:
            name: Komponent nomi
            check_fn: Tekshirish funksiyasi → ComponentHealth qaytaradi
        """
        self._checks[name] = check_fn
        log.info("health.registered", component=name)

    def check_all(self) -> HealthReport:
        """Barcha komponentlarni tekshirish.

        Returns:
            HealthReport — umumiy hisobot
        """
        components: list[ComponentHealth] = []

        for name, check_fn in self._checks.items():
            try:
                result = check_fn()
                components.append(result)
            except Exception as exc:
                components.append(
                    ComponentHealth(
                        name=name,
                        status=ComponentStatus.UNHEALTHY,
                        message=f"Tekshirish xatosi: {exc}",
                    )
                )

        # Eng yomon holat
        if not components:
            overall = ComponentStatus.UNKNOWN
        elif any(c.status == ComponentStatus.UNHEALTHY for c in components):
            overall = ComponentStatus.UNHEALTHY
        elif any(c.status == ComponentStatus.DEGRADED for c in components):
            overall = ComponentStatus.DEGRADED
        elif any(c.status == ComponentStatus.UNKNOWN for c in components):
            overall = ComponentStatus.UNKNOWN
        else:
            overall = ComponentStatus.HEALTHY

        report = HealthReport(
            status=overall,
            components=components,
        )

        if not report.is_healthy:
            log.warning(
                "health.degraded",
                status=overall.value,
                unhealthy=[c.name for c in report.unhealthy_components],
            )

        return report

    def check_one(self, name: str) -> ComponentHealth | None:
        """Bitta komponentni tekshirish.

        Args:
            name: Komponent nomi

        Returns:
            ComponentHealth yoki None agar topilmasa
        """
        check_fn = self._checks.get(name)
        if check_fn is None:
            return None
        try:
            return check_fn()
        except Exception as exc:
            return ComponentHealth(
                name=name,
                status=ComponentStatus.UNHEALTHY,
                message=f"Tekshirish xatosi: {exc}",
            )

    @property
    def registered_components(self) -> list[str]:
        """Ro'yxatga olingan komponentlar."""
        return list(self._checks.keys())


# Type alias — pastda, chunki ComponentHealth kerak
type _HealthCheckFn = Callable[[], ComponentHealth]
