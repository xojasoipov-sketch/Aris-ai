"""ZET konfiguratsiyasi.

Qatlamlar: default -> `.env` -> environment o'zgaruvchilari.
Barcha sirlar `SecretStr` tipida — ular `repr()` va log'da hech qachon ochilmaydi.

Bog'liq qarorlar:
    ADR-0006 — model tier'lari va budjet chegaralari
    ADR-0007 — local-first deployment
"""

from __future__ import annotations

import functools
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[4]


class Env(StrEnum):
    """Ishga tushirish muhiti."""

    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class Settings(BaseSettings):
    """ZET yadrosining to'liq konfiguratsiyasi.

    `ZET_` prefiksli environment o'zgaruvchilaridan o'qiladi.
    """

    model_config = SettingsConfigDict(
        env_prefix="ZET_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # ── Ilova ──────────────────────────────────────────────────────
    env: Env = Env.DEV
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    timezone: str = "Asia/Tashkent"

    # ── Ma'lumotlar bazasi / navbat ────────────────────────────────
    database_url: SecretStr = SecretStr("postgresql+asyncpg://zet:zet@localhost:5432/zet")
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")

    # ── LLM provayderlar (ADR-0006: T0 -> T1 -> T2 -> T3) ──────────
    # T0 — lokal (bepul)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    ollama_embed_model: str = "bge-m3"
    # T1 — free tier
    google_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    mistral_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    # T2 / T3 — to'lovli
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    # ── Budjet chegaralari (ADR-0006 §4, fail-closed) ──────────────
    budget_monthly_usd: float = Field(default=10.0, ge=0)
    budget_daily_usd: float = Field(default=0.50, ge=0)
    run_max_usd: float = Field(default=0.10, ge=0)
    tier3_daily_calls: int = Field(default=5, ge=0)
    autonomous_budget_share: float = Field(default=0.40, ge=0, le=1)

    # ── Run chegaralari (A-07: avtomatlashtirish tormozlari) ───────
    run_max_steps: int = Field(default=20, ge=1)
    run_max_depth: int = Field(default=3, ge=1)
    run_timeout_s: int = Field(default=600, ge=1)

    # ── Xavfsizlik ─────────────────────────────────────────────────
    owner_id: str = "owner"
    api_token: SecretStr | None = None
    approval_ttl_minutes: int = Field(default=30, ge=1)
    enable_shell: bool = False
    """`shell.exec` tooli. Default o'chirilgan — Z1.10 dagi eng xavfli komponent."""

    # ── Yo'llar ────────────────────────────────────────────────────
    data_dir: Path = _REPO_ROOT / "data"
    vault_dir: Path = _REPO_ROOT / "vault"

    @field_validator("database_url", "redis_url")
    @classmethod
    def _not_empty(cls, v: SecretStr) -> SecretStr:
        if not v.get_secret_value().strip():
            raise ValueError("bo'sh bo'lishi mumkin emas")
        return v

    @model_validator(mode="after")
    def _check_budget_coherence(self) -> Settings:
        if self.budget_daily_usd > self.budget_monthly_usd:
            raise ValueError(
                f"budget_daily_usd ({self.budget_daily_usd}) "
                f"budget_monthly_usd ({self.budget_monthly_usd}) dan katta bo'lishi mumkin emas"
            )
        if self.run_max_usd > self.budget_daily_usd:
            raise ValueError(
                f"run_max_usd ({self.run_max_usd}) "
                f"budget_daily_usd ({self.budget_daily_usd}) dan katta bo'lishi mumkin emas"
            )
        return self

    @model_validator(mode="after")
    def _check_prod_requirements(self) -> Settings:
        if self.env is Env.PROD:
            missing: list[str] = []
            if self.api_token is None:
                missing.append("ZET_API_TOKEN")
            if not self.has_any_llm_provider:
                missing.append("kamida bitta LLM provayder kaliti yoki Ollama")
            if missing:
                raise ValueError(f"prod muhitida majburiy: {', '.join(missing)}")
        return self

    @property
    def has_any_llm_provider(self) -> bool:
        """Kamida bitta LLM yo'li mavjudmi (lokal Ollama ham hisoblanadi)."""
        return any(
            [
                self.google_api_key,
                self.groq_api_key,
                self.mistral_api_key,
                self.openrouter_api_key,
                self.anthropic_api_key,
                self.openai_api_key,
                bool(self.ollama_base_url),
            ]
        )

    @property
    def is_prod(self) -> bool:
        return self.env is Env.PROD

    @property
    def autonomous_daily_budget_usd(self) -> float:
        """Jadval bo'yicha ishlaydigan run'larga ajratilgan kunlik ulush (ADR-0006 §4)."""
        return self.budget_daily_usd * self.autonomous_budget_share


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Keshlangan sozlamalar (protsess davomida bir marta o'qiladi)."""
    return Settings()
