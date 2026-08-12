"""Provayder qamrovi testlari (Z42).

Bu fayl bitta aniq xato turini qaytib kelishidan saqlaydi:
**konfiguratsiyada kalit bor, lekin `build_providers()` uni qurmaydi.**

Aynan shu holat `openrouter` bilan sodir bo'lgan edi — `Settings`da
`openrouter_api_key` yillab turgan, ega uni `.env`ga yozsa ham hech
narsa ishlamasdi, chunki factory uni umuman yaratmasdi va xato ham
bermasdi. Jimgina ishlamaslik — eng yomon nosozlik turi.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from zet.config import Settings
from zet.domain.enums import TaskClass
from zet.llm.catalog import CATALOG, ROUTING
from zet.llm.factory import build_providers

# `Settings`dagi kalit maydoni -> `build_providers()` dagi provayder nomi.
KEY_TO_PROVIDER: dict[str, str] = {
    "google_api_key": "google",
    "groq_api_key": "groq",
    "mistral_api_key": "mistral",
    "openrouter_api_key": "openrouter",
    "cohere_api_key": "cohere",
    "cerebras_api_key": "cerebras",
    "deepseek_api_key": "deepseek",
    "kimi_api_key": "kimi",
    "anthropic_api_key": "anthropic",
}


def _settings(**kwargs: object) -> Settings:
    """Test Settings — barcha LLM kalitlari ANIQ bo'shatiladi.

    `.env` faylining ta'sirini yo'q qiladi, aks holda test ishlab
    chiquvchining mashinasiga bog'liq bo'lardi.
    """
    base: dict[str, object] = dict.fromkeys(KEY_TO_PROVIDER)
    base["openai_api_key"] = None
    base.update(kwargs)
    return Settings.model_validate(base)


class TestEveryKeyHasAProvider:
    """Har bir kalit maydoni haqiqiy provayderga ulangan."""

    @pytest.mark.parametrize(("key_field", "provider_name"), sorted(KEY_TO_PROVIDER.items()))
    def test_key_builds_a_configured_provider(self, key_field: str, provider_name: str) -> None:
        """Kalit berilsa — provayder `is_configured=True` bo'ladi.

        Bu `openrouter` turidagi jim teshikni ushlaydi: kalit bor, lekin
        factory uni qurmaydi.
        """
        providers = build_providers(_settings(**{key_field: "test-key"}))

        assert provider_name in providers, f"'{provider_name}' factory'da qurilmagan"
        assert providers[provider_name].is_configured is True

    def test_provider_is_unconfigured_without_key(self) -> None:
        """Kalitsiz provayder yaratiladi, lekin router uni o'tkazib yuboradi."""
        providers = build_providers(_settings())

        for name in KEY_TO_PROVIDER.values():
            assert name in providers
            assert providers[name].is_configured is False, name


class TestCatalogConsistency:
    """Katalog va factory bir-biriga mos."""

    def test_every_catalog_model_has_a_provider(self) -> None:
        """Katalogdagi har bir model qurilgan provayderga ishora qiladi."""
        providers = build_providers(_settings())

        for key, spec in CATALOG.items():
            assert spec.provider in providers, f"'{key}' provayderi yo'q: {spec.provider}"

    def test_every_routed_key_exists_in_catalog(self) -> None:
        """Marshrutdagi har bir kalit katalogda bor (nomi xato yozilmagan)."""
        for task_class, keys in ROUTING.items():
            for key in keys:
                assert key in CATALOG, f"{task_class.value}: '{key}' katalogda yo'q"

    def test_every_task_class_has_candidates(self) -> None:
        """Har bir vazifa sinfi uchun kamida bitta nomzod bor."""
        for task_class in TaskClass:
            assert ROUTING.get(task_class), task_class.value

    def test_routing_has_no_duplicates_within_a_class(self) -> None:
        """Bitta sinf ichida model ikki marta sanalmaydi."""
        for task_class, keys in ROUTING.items():
            assert len(keys) == len(set(keys)), task_class.value


class TestUnfundedProvidersArePlacedLast:
    """Balanssiz provayderlar kundalik yo'lni sekinlashtirmaydi.

    2026-08-12 jonli tekshiruvi: cerebras/deepseek/kimi kalitlari
    yaroqli, lekin hisoblari bo'sh. Ular zanjirdan olib tashlanmadi
    (hisob to'ldirilgach o'zi ishlasin), lekin ishlaydigan provayderdan
    OLDIN turmasligi kerak.
    """

    UNFUNDED: ClassVar[set[str]] = {"cerebras", "deepseek", "kimi"}
    VERIFIED_WORKING: ClassVar[set[str]] = {"google", "mistral", "cohere"}

    def test_unfunded_never_precede_verified_providers(self) -> None:
        for task_class, keys in ROUTING.items():
            providers = [CATALOG[k].provider for k in keys]
            for i, provider in enumerate(providers):
                if provider not in self.UNFUNDED:
                    continue
                later = set(providers[i + 1 :])
                assert not (later & self.VERIFIED_WORKING), (
                    f"{task_class.value}: balanssiz '{provider}' "
                    f"ishlaydigan {later & self.VERIFIED_WORKING} dan oldin turibdi"
                )
