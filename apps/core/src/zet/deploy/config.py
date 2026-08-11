"""Deployment Config — produksiya sozlamalari (Bo'lim 12).

Local-first deployment: eganing kompyuterida native service sifatida.
Konfiguratsiya .env fayldan o'qiladi, har bir sozlama tekshiriladi.

Muhit turlari:
    - DEV — ishlab chiqish (default)
    - STAGING — test muhiti
    - PRODUCTION — produksiya

Bog'liq qarorlar:
    Bo'lim 12 — Production + Scale
    ADR-0007 — local-first deployment
"""

from __future__ import annotations

import os
from enum import StrEnum

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)


class Environment(StrEnum):
    """Muhit turi."""

    DEV = "dev"
    """Ishlab chiqish."""

    STAGING = "staging"
    """Test muhiti."""

    PRODUCTION = "production"
    """Produksiya."""


class DeployConfig(BaseModel, frozen=True):
    """Deployment konfiguratsiyasi.

    Barcha sozlamalar .env fayldan o'qiladi.
    Default qiymatlar xavfsiz (DEV muhiti).
    """

    environment: Environment = Environment.DEV
    """Muhit turi."""

    host: str = "127.0.0.1"
    """Server host."""

    port: int = Field(default=8000, ge=1, le=65535)
    """Server port."""

    debug: bool = False
    """Debug rejimi."""

    log_level: str = "INFO"
    """Log darajasi."""

    db_url: str = "sqlite+aiosqlite:///./zet.db"
    """Ma'lumotlar bazasi URL."""

    telegram_bot_token: str = ""
    """Telegram bot tokeni (produksiyada majburiy)."""

    monthly_budget_usd: float = Field(default=10.0, ge=0)
    """Oylik budjet ($). Default: $10."""

    max_concurrent_runs: int = Field(default=3, ge=1, le=10)
    """Bir vaqtda ishlashi mumkin bo'lgan runlar."""

    backup_enabled: bool = False
    """Backup yoqilganmi."""

    backup_interval_hours: int = Field(default=24, ge=1)
    """Backup orasidagi vaqt (soatda)."""

    caddy_enabled: bool = False
    """Caddy reverse proxy yoqilganmi."""

    caddy_domain: str = ""
    """Caddy uchun domen nomi."""

    @property
    def is_production(self) -> bool:
        """Produksiya muhitidami."""
        return self.environment == Environment.PRODUCTION

    @property
    def is_dev(self) -> bool:
        """Ishlab chiqish muhitidami."""
        return self.environment == Environment.DEV


def load_config() -> DeployConfig:
    """Muhit o'zgaruvchilaridan konfiguratsiya yuklash.

    Returns:
        DeployConfig
    """
    env = os.environ.get("ZET_ENV", "dev")
    config = DeployConfig(
        environment=Environment(env)
        if env in Environment.__members__.values()
        else Environment.DEV,
        host=os.environ.get("ZET_HOST", "127.0.0.1"),
        port=int(os.environ.get("ZET_PORT", "8000")),
        debug=os.environ.get("ZET_DEBUG", "").lower() in ("1", "true", "yes"),
        log_level=os.environ.get("ZET_LOG_LEVEL", "INFO"),
        db_url=os.environ.get("ZET_DB_URL", "sqlite+aiosqlite:///./zet.db"),
        telegram_bot_token=os.environ.get("ZET_TELEGRAM_TOKEN", ""),
        monthly_budget_usd=float(os.environ.get("ZET_MONTHLY_BUDGET", "10.0")),
        max_concurrent_runs=int(os.environ.get("ZET_MAX_RUNS", "3")),
        backup_enabled=os.environ.get("ZET_BACKUP", "").lower() in ("1", "true", "yes"),
        backup_interval_hours=int(os.environ.get("ZET_BACKUP_INTERVAL", "24")),
        caddy_enabled=os.environ.get("ZET_CADDY", "").lower() in ("1", "true", "yes"),
        caddy_domain=os.environ.get("ZET_CADDY_DOMAIN", ""),
    )

    log.info(
        "deploy.config_loaded",
        environment=config.environment.value,
        host=config.host,
        port=config.port,
    )
    return config


def validate_production_config(config: DeployConfig) -> list[str]:
    """Produksiya konfiguratsiyasini tekshirish.

    Args:
        config: Tekshiriladigan konfiguratsiya

    Returns:
        Xatolar ro'yxati (bo'sh = hammasi yaxshi)
    """
    errors: list[str] = []

    if config.is_production:
        if not config.telegram_bot_token:
            errors.append("Produksiyada TELEGRAM_BOT_TOKEN majburiy")
        if config.debug:
            errors.append("Produksiyada DEBUG o'chirilgan bo'lishi kerak")
        if config.host == "0.0.0.0" and not config.caddy_enabled:  # noqa: S104
            errors.append("0.0.0.0 da tinglash — Caddy kerak")
        if not config.backup_enabled:
            errors.append("Produksiyada backup yoqilgan bo'lishi kerak")

    return errors
