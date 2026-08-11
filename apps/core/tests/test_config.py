"""Z1.2 — konfiguratsiya testlari.

Asosiy talab: sirlar hech qachon `repr()` yoki log'da ochilmasligi kerak.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from zet.config import Env, Settings


def _settings(**overrides: object) -> Settings:
    """Environment'dan mustaqil, faqat berilgan qiymatlar bilan Settings."""
    base: dict[str, object] = {"_env_file": None}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestDefaults:
    def test_default_env_is_dev(self) -> None:
        assert _settings().env is Env.DEV

    def test_default_budget_matches_adr_0006(self) -> None:
        s = _settings()
        assert s.budget_monthly_usd == 10.0
        assert s.budget_daily_usd == 0.50
        assert s.run_max_usd == 0.10
        assert s.tier3_daily_calls == 5

    def test_shell_disabled_by_default(self) -> None:
        assert _settings().enable_shell is False

    def test_autonomous_share_computed(self) -> None:
        s = _settings(budget_daily_usd=1.0, autonomous_budget_share=0.4)
        assert s.autonomous_daily_budget_usd == pytest.approx(0.4)


class TestSecretsAreNeverLeaked:
    """Eng muhim test: sir hech qanday matn ko'rinishida chiqmasligi kerak."""

    SECRET = "sk-super-maxfiy-kalit-12345"

    def test_secret_hidden_in_repr(self) -> None:
        s = _settings(anthropic_api_key=self.SECRET)
        assert self.SECRET not in repr(s)

    def test_secret_hidden_in_str(self) -> None:
        s = _settings(anthropic_api_key=self.SECRET)
        assert self.SECRET not in str(s)

    def test_secret_hidden_in_model_dump(self) -> None:
        s = _settings(anthropic_api_key=self.SECRET)
        assert self.SECRET not in str(s.model_dump())

    def test_secret_hidden_in_json(self) -> None:
        s = _settings(anthropic_api_key=self.SECRET)
        assert self.SECRET not in s.model_dump_json()

    def test_database_url_is_secret(self) -> None:
        url = "postgresql+asyncpg://zet:PAROL@host/db"
        s = _settings(database_url=url)
        assert "PAROL" not in repr(s)
        assert s.database_url.get_secret_value() == url


class TestValidation:
    def test_daily_budget_cannot_exceed_monthly(self) -> None:
        with pytest.raises(ValidationError, match="budget_monthly_usd"):
            _settings(budget_monthly_usd=5.0, budget_daily_usd=10.0)

    def test_run_max_cannot_exceed_daily(self) -> None:
        with pytest.raises(ValidationError, match="budget_daily_usd"):
            _settings(budget_daily_usd=0.5, run_max_usd=1.0)

    def test_negative_budget_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _settings(budget_daily_usd=-1.0)

    def test_empty_database_url_rejected(self) -> None:
        with pytest.raises(ValidationError, match="bo'sh"):
            _settings(database_url="   ")

    def test_invalid_log_level_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _settings(log_level="TRACE")

    def test_run_max_steps_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            _settings(run_max_steps=0)


class TestProdRequirements:
    def test_prod_requires_api_token(self) -> None:
        with pytest.raises(ValidationError, match="ZET_API_TOKEN"):
            _settings(env="prod", api_token=None, anthropic_api_key="k")

    def test_prod_ok_with_token_and_provider(self) -> None:
        s = _settings(env="prod", api_token="tok", anthropic_api_key="k")
        assert s.is_prod is True

    def test_dev_needs_nothing(self) -> None:
        assert _settings(env="dev").is_prod is False


class TestProviders:
    def test_ollama_counts_as_provider(self) -> None:
        """T0 (lokal) ham to'liq huquqli provayder — ADR-0006."""
        assert _settings().has_any_llm_provider is True

    def test_no_provider_when_ollama_empty(self) -> None:
        s = _settings(ollama_base_url="")
        assert s.has_any_llm_provider is False

    def test_free_tier_key_counts(self) -> None:
        s = _settings(ollama_base_url="", google_api_key="g")
        assert s.has_any_llm_provider is True


class TestImmutability:
    def test_settings_are_frozen(self) -> None:
        s = _settings()
        with pytest.raises(ValidationError):
            s.budget_daily_usd = 999.0  # type: ignore[misc]
