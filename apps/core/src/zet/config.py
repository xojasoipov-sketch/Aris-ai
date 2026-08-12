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

    # ── Telegram (Bo'lim 5, V-17) ───────────────────────────────────
    telegram_bot_token: SecretStr | None = None
    """Telegram bot token. `.env` faylida saqlang — hech qachon kodda emas."""

    telegram_owner_ids: str = ""
    """Vergul bilan ajratilgan Telegram user ID lar (owner allowlist, R-04).

    Misol: "123456789,987654321"
    Bo'sh bo'lsa — hech kimga ruxsat yo'q (fail-closed).
    """

    # ── GitHub (Bo'lim 7) ────────────────────────────────────────────
    github_token: SecretStr | None = None
    """GitHub Personal Access Token. Bo'lsa — `github.read`/`github.write`
    haqiqiy API'ga chiqadi; bo'lmasa — stub rejimda ishlaydi."""

    # ── Web qidiruv (Bo'lim 7) ────────────────────────────────────────
    web_search_api_key: SecretStr | None = None
    """Brave Search API kaliti (bepul qatlam: 2000 so'rov/oy). Bo'lsa —
    `web.search` haqiqiy qidiradi; bo'lmasa — stub rejimda ishlaydi."""

    # ── Kamera (Bo'lim 8) ─────────────────────────────────────────────
    hikvision_host: str = ""
    """Hikvision kamera/NVR manzili (masalan '192.168.1.64' yoki '...:80').
    Bo'lsa (username/password bilan birga) — `camera.snapshot` haqiqiy
    ISAPI snapshot'ga chiqadi; bo'lmasa — StubCamera ishlaydi."""

    hikvision_username: str = ""
    """Hikvision ISAPI foydalanuvchi nomi (odatda 'admin')."""

    hikvision_password: SecretStr | None = None
    """Hikvision ISAPI paroli."""

    hikvision_channel: int = Field(default=1, ge=1)
    """Kamera kanal raqami (NVR uchun 101, 201, ...; yagona kamera uchun 1)."""

    # ── Xavfsizlik ─────────────────────────────────────────────────
    owner_id: str = "owner"
    api_token: SecretStr | None = None
    approval_ttl_minutes: int = Field(default=30, ge=1)
    enable_shell: bool = False
    """`shell.exec` tooli. Default o'chirilgan — Z1.10 dagi eng xavfli komponent."""

    # ── Yo'llar ────────────────────────────────────────────────────
    data_dir: Path = _REPO_ROOT / "data"

    vault_dir: Path = _REPO_ROOT / "vault"
    """Obsidian vault papkasi — `note.write`/`note.read`/`note.list` shu yerda
    ishlaydi. `ZET_VAULT_DIR` orqali o'z vault'ingizga yo'naltiriladi."""

    @model_validator(mode="before")
    @classmethod
    def _blank_paths_use_default(cls, data: object) -> object:
        """Bo'sh `ZET_VAULT_DIR=` ni `Path('.')` ga aylantirmaslik uchun.

        Aks holda vault butun repo bo'lib qolardi — `note.list` manba
        daraxtidagi har bir `.md` ni ko'rar, `note.write` esa kodning
        ichiga yozardi. Bo'sh qiymat butunlay olib tashlanadi, shunda
        maydonning o'z default'i qo'llanadi.
        """
        if not isinstance(data, dict):
            return data
        return {
            key: value
            for key, value in data.items()
            if not (
                key.lower().removeprefix("zet_") in {"data_dir", "vault_dir"}
                and isinstance(value, str)
                and not value.strip()
            )
        }

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
    def telegram_owner_id_set(self) -> set[int]:
        """Telegram owner ID larni set ga o'girish."""
        if not self.telegram_owner_ids.strip():
            return set()
        result: set[int] = set()
        for part in self.telegram_owner_ids.split(","):
            part = part.strip()
            if part.isdigit():
                result.add(int(part))
        return result

    @property
    def autonomous_daily_budget_usd(self) -> float:
        """Jadval bo'yicha ishlaydigan run'larga ajratilgan kunlik ulush (ADR-0006 §4)."""
        return self.budget_daily_usd * self.autonomous_budget_share


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Keshlangan sozlamalar (protsess davomida bir marta o'qiladi)."""
    return Settings()
