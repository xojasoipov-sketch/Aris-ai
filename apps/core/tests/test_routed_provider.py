"""llm/routed_provider.py testlari — ModelRouter'ni LLMProvider'ga moslash.

`conftest.py`dagi `session` fixture'i orqali real (in-memory sqlite) DB'ga
ulangan `ModelRouter` bilan ishlaydi (budjet/kvota kuzatuvi haqiqiy).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from zet.config import Settings
from zet.domain.enums import ModelTier, TaskClass
from zet.llm.base import ChatMessage
from zet.llm.fake import FakeProvider
from zet.llm.routed_provider import RoutedLLMProvider, task_class_for_tier
from zet.llm.router import ModelRouter


class TestTaskClassForTier:
    def test_all_tiers_mapped(self) -> None:
        for tier in ModelTier:
            assert task_class_for_tier(tier) in TaskClass

    def test_t0_maps_to_simple(self) -> None:
        assert task_class_for_tier(ModelTier.T0_LOCAL) == TaskClass.SIMPLE

    def test_t1_maps_to_normal(self) -> None:
        assert task_class_for_tier(ModelTier.T1_FREE) == TaskClass.NORMAL

    def test_t2_and_t3_map_to_complex(self) -> None:
        assert task_class_for_tier(ModelTier.T2_CHEAP) == TaskClass.COMPLEX
        assert task_class_for_tier(ModelTier.T3_STRONG) == TaskClass.COMPLEX


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)


@pytest.fixture
def fake_google() -> FakeProvider:
    return FakeProvider(name="google", tier=ModelTier.T1_FREE)


@pytest.fixture
def router(session: AsyncSession, settings: Settings, fake_google: FakeProvider) -> ModelRouter:
    return ModelRouter({"google": fake_google}, session, settings)


class TestComplete:
    async def test_routes_via_task_class(
        self, router: ModelRouter, fake_google: FakeProvider
    ) -> None:
        provider = RoutedLLMProvider(router)
        response = await provider.complete(
            model="normal",
            messages=[ChatMessage(role="user", content="Salom")],
        )
        assert "Salom" in response.text
        assert fake_google.calls  # haqiqatan chaqirilgan

    async def test_invalid_model_string_falls_back_to_normal(
        self, router: ModelRouter, fake_google: FakeProvider
    ) -> None:
        provider = RoutedLLMProvider(router)
        await provider.complete(
            model="not-a-real-task-class",
            messages=[ChatMessage(role="user", content="Salom")],
        )
        assert fake_google.calls  # baribir marshrutlandi (NORMAL orqali)

    async def test_is_configured_always_true(self, router: ModelRouter) -> None:
        assert RoutedLLMProvider(router).is_configured is True

    async def test_aclose_is_noop(self, router: ModelRouter) -> None:
        provider = RoutedLLMProvider(router)
        await provider.aclose()  # xato ko'tarmasligi kerak

    async def test_no_provider_available_propagates(
        self, session: AsyncSession, settings: Settings
    ) -> None:
        """Hech qanday provayder sozlanmagan bo'lsa — xato AgentRuntime'ga ko'tariladi."""
        from zet.llm.base import NoProviderAvailableError

        empty_router = ModelRouter({}, session, settings)
        provider = RoutedLLMProvider(empty_router)
        with pytest.raises(NoProviderAvailableError):
            await provider.complete(
                model="normal", messages=[ChatMessage(role="user", content="Salom")]
            )
