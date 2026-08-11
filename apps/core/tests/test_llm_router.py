"""Z1.5 — Model Router, kvota va budjet testlari.

Bu Bo'lim 1 ning eng muhim testlari: $10 budjetda ZET ishlashi shu mantiqqa bog'liq.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zet.config import Settings
from zet.db.models import CostLedger, QuotaLedger
from zet.domain.enums import ModelTier, TaskClass
from zet.llm.base import (
    BudgetExceededError,
    ChatMessage,
    NoProviderAvailableError,
    ProviderUnavailableError,
    RateLimitError,
    ToolSpec,
    Usage,
)
from zet.llm.budget import BudgetGuard
from zet.llm.catalog import CATALOG, ROUTING, candidates_for
from zet.llm.fake import FakeProvider, fake_response
from zet.llm.quota import QuotaManager
from zet.llm.router import ModelRouter

FIXED_NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
MESSAGES = [ChatMessage(role="user", content="Salom")]


def make_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "_env_file": None,
        "budget_monthly_usd": 10.0,
        "budget_daily_usd": 0.50,
        "run_max_usd": 0.10,
        "tier3_daily_calls": 5,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def all_providers(**overrides: FakeProvider) -> dict[str, FakeProvider]:
    """Katalogdagi har bir provayder uchun soxta implementatsiya."""
    providers = {
        "ollama": FakeProvider("ollama", ModelTier.T0_LOCAL),
        "google": FakeProvider("google", ModelTier.T1_FREE),
        "groq": FakeProvider("groq", ModelTier.T1_FREE),
        "mistral": FakeProvider("mistral", ModelTier.T1_FREE),
        "anthropic": FakeProvider("anthropic", ModelTier.T2_CHEAP),
    }
    providers.update(overrides)
    return providers


def make_router(
    session: AsyncSession,
    providers: dict[str, FakeProvider] | None = None,
    settings: Settings | None = None,
    now: datetime = FIXED_NOW,
) -> ModelRouter:
    def clock() -> datetime:
        return now

    return ModelRouter(
        providers or all_providers(),
        session,
        settings or make_settings(),
        now_fn=clock,
    )


# ── Katalog ────────────────────────────────────────────────────────


class TestCatalog:
    def test_every_routing_key_exists(self) -> None:
        """Marshrut jadvalida yo'q model bo'lmasligi kerak."""
        for task_class, keys in ROUTING.items():
            for key in keys:
                assert key in CATALOG, f"{task_class}: {key} katalogda yo'q"

    def test_every_task_class_has_candidates(self) -> None:
        for task_class in TaskClass:
            assert ROUTING.get(task_class), f"{task_class} uchun nomzod yo'q"

    def test_no_paid_model_before_a_free_one(self) -> None:
        """Budjetni himoya qiluvchi asosiy invariant.

        T0 va T1 ikkalasi ham bepul, shuning uchun ular orasidagi tartib
        **sifat** bo'yicha tanlanadi (NORMAL da bulutli free tier lokal 8B dan
        kuchliroq). Lekin bepul modelidan oldin pullik model turishi mumkin emas —
        `COMPLEX`/`CODING` dan tashqari, u yerda sifat ataylab birinchi o'rinda.
        """
        for task_class in (TaskClass.SIMPLE, TaskClass.NORMAL, TaskClass.VISION):
            seen_paid = False
            for spec in candidates_for(task_class):
                if spec.is_free:
                    assert not seen_paid, (
                        f"{task_class}: bepul {spec.key} pullik modeldan keyin turibdi"
                    )
                else:
                    seen_paid = True

    def test_complex_starts_with_strong_model(self) -> None:
        """Planner sifati — ADR-0006 da ataylab qilingan istisno."""
        first = candidates_for(TaskClass.COMPLEX)[0]
        assert first.tier is ModelTier.T3_STRONG

    def test_complex_has_free_fallback(self) -> None:
        """Kuchli model kunlik limitga yetganda ish to'xtamasligi kerak."""
        assert any(spec.is_free for spec in candidates_for(TaskClass.COMPLEX))

    def test_free_models_cost_nothing(self) -> None:
        for spec in CATALOG.values():
            if spec.tier in (ModelTier.T0_LOCAL, ModelTier.T1_FREE):
                assert spec.is_free, f"{spec.key} bepul bo'lishi kerak"

    def test_paid_models_have_prices(self) -> None:
        for spec in CATALOG.values():
            if spec.tier in (ModelTier.T2_CHEAP, ModelTier.T3_STRONG):
                assert spec.input_usd_per_mtok > 0, spec.key
                assert spec.output_usd_per_mtok > 0, spec.key

    def test_cost_calculation(self) -> None:
        spec = CATALOG["anthropic:haiku"]
        # 1M kirish * $1 + 1M chiqish * $5 = $6
        assert spec.cost_usd(Usage(1_000_000, 1_000_000)) == pytest.approx(6.0)

    def test_adr_0006_run_cost_estimate(self) -> None:
        """ADR-0006 dagi hisob: 25k kirish + 3.6k chiqish."""
        usage = Usage(25_000, 3_600)
        assert CATALOG["anthropic:haiku"].cost_usd(usage) == pytest.approx(0.043, abs=0.001)
        assert CATALOG["anthropic:sonnet"].cost_usd(usage) == pytest.approx(0.129, abs=0.001)
        assert CATALOG["ollama:qwen3-8b"].cost_usd(usage) == 0.0


# ── Marshrutlash ───────────────────────────────────────────────────


class TestRouting:
    async def test_simple_goes_to_local_first(self, session: AsyncSession) -> None:
        result = await make_router(session).complete(task_class=TaskClass.SIMPLE, messages=MESSAGES)
        assert result.spec.tier is ModelTier.T0_LOCAL
        assert result.cost_usd == 0.0

    async def test_normal_goes_to_free_tier(self, session: AsyncSession) -> None:
        result = await make_router(session).complete(task_class=TaskClass.NORMAL, messages=MESSAGES)
        assert result.spec.tier is ModelTier.T1_FREE
        assert result.cost_usd == 0.0

    async def test_unconfigured_provider_is_skipped(self, session: AsyncSession) -> None:
        providers = all_providers(
            ollama=FakeProvider("ollama", ModelTier.T0_LOCAL, configured=False)
        )
        result = await make_router(session, providers).complete(
            task_class=TaskClass.SIMPLE, messages=MESSAGES
        )
        assert result.spec.provider != "ollama"
        assert any("sozlanmagan" in s.reason for s in result.skipped)

    async def test_falls_over_on_rate_limit(self, session: AsyncSession) -> None:
        providers = all_providers(
            ollama=FakeProvider("ollama", ModelTier.T0_LOCAL, scripted=[RateLimitError("429")])
        )
        result = await make_router(session, providers).complete(
            task_class=TaskClass.SIMPLE, messages=MESSAGES
        )
        assert result.spec.provider == "google"
        assert any("RateLimitError" in s.reason for s in result.skipped)

    async def test_falls_over_on_unavailable(self, session: AsyncSession) -> None:
        providers = all_providers(
            google=FakeProvider(
                "google", ModelTier.T1_FREE, scripted=[ProviderUnavailableError("503")]
            )
        )
        result = await make_router(session, providers).complete(
            task_class=TaskClass.NORMAL, messages=MESSAGES
        )
        assert result.spec.provider == "groq"

    async def test_no_provider_raises(self, session: AsyncSession) -> None:
        providers = {
            name: FakeProvider(name, ModelTier.T0_LOCAL, configured=False)
            for name in ("ollama", "google", "groq", "mistral", "anthropic")
        }
        with pytest.raises(NoProviderAvailableError, match="provayder topilmadi"):
            await make_router(session, providers).complete(
                task_class=TaskClass.SIMPLE, messages=MESSAGES
            )

    async def test_tool_support_filters_candidates(self, session: AsyncSession) -> None:
        """Tool kerak bo'lsa, tool-calling qo'llamaydigan model o'tkazib yuboriladi."""
        tools = [ToolSpec(name="time.now", description="vaqt", input_schema={})]
        result = await make_router(session).complete(
            task_class=TaskClass.SIMPLE, messages=MESSAGES, tools=tools
        )
        assert result.spec.supports_tools

    async def test_provider_receives_correct_model_name(self, session: AsyncSession) -> None:
        providers = all_providers()
        await make_router(session, providers).complete(
            task_class=TaskClass.SIMPLE, messages=MESSAGES
        )
        assert providers["ollama"].calls[0]["model"] == "qwen3:8b"


# ── Circuit breaker ────────────────────────────────────────────────


class TestCircuitBreaker:
    async def test_opens_after_threshold(self, session: AsyncSession) -> None:
        ollama = FakeProvider(
            "ollama",
            ModelTier.T0_LOCAL,
            scripted=[ProviderUnavailableError("x") for _ in range(3)],
        )
        router = make_router(session, all_providers(ollama=ollama))

        for _ in range(3):
            await router.complete(task_class=TaskClass.SIMPLE, messages=MESSAGES)

        ollama.push(fake_response("endi ishlayapman"))
        result = await router.complete(task_class=TaskClass.SIMPLE, messages=MESSAGES)

        assert result.spec.provider != "ollama"
        assert any("circuit breaker" in s.reason for s in result.skipped)

    async def test_closes_after_cooldown(self, session: AsyncSession) -> None:
        now = FIXED_NOW
        ollama = FakeProvider(
            "ollama",
            ModelTier.T0_LOCAL,
            scripted=[ProviderUnavailableError("x") for _ in range(3)],
        )
        providers = all_providers(ollama=ollama)
        router = ModelRouter(providers, session, make_settings(), now_fn=lambda: now)
        for _ in range(3):
            await router.complete(task_class=TaskClass.SIMPLE, messages=MESSAGES)

        later = FIXED_NOW + timedelta(seconds=ModelRouter.BREAKER_COOLDOWN_S + 1)
        router._now = lambda: later
        result = await router.complete(task_class=TaskClass.SIMPLE, messages=MESSAGES)
        assert result.spec.provider == "ollama"

    async def test_success_resets_failures(self, session: AsyncSession) -> None:
        ollama = FakeProvider(
            "ollama",
            ModelTier.T0_LOCAL,
            scripted=[ProviderUnavailableError("x"), ProviderUnavailableError("x")],
        )
        router = make_router(session, all_providers(ollama=ollama))
        for _ in range(2):
            await router.complete(task_class=TaskClass.SIMPLE, messages=MESSAGES)
        # 3-chaqiruv muvaffaqiyatli -> hisoblagich nolga tushadi
        await router.complete(task_class=TaskClass.SIMPLE, messages=MESSAGES)

        ollama.push(ProviderUnavailableError("x"))
        result = await router.complete(task_class=TaskClass.SIMPLE, messages=MESSAGES)
        assert not any("circuit breaker" in s.reason for s in result.skipped)


# ── Kvota ──────────────────────────────────────────────────────────


class TestQuota:
    async def test_records_use(self, session: AsyncSession) -> None:
        await make_router(session).complete(task_class=TaskClass.NORMAL, messages=MESSAGES)
        rows = (await session.execute(select(QuotaLedger))).scalars().all()
        assert {r.window for r in rows} == {"day", "minute"}
        assert all(r.used == 1 for r in rows)

    async def test_local_tier_has_no_quota_rows(self, session: AsyncSession) -> None:
        """Lokal model cheklanmaydi — hisobga olish shart emas."""
        await make_router(session).complete(task_class=TaskClass.SIMPLE, messages=MESSAGES)
        rows = (await session.execute(select(QuotaLedger))).scalars().all()
        assert rows == []

    async def test_exhausted_quota_skips_provider(self, session: AsyncSession) -> None:
        spec = CATALOG["google:gemini-flash"]
        assert spec.free_rpm is not None
        quota = QuotaManager(session)
        for _ in range(spec.free_rpm):
            await quota.record_use(spec, now=FIXED_NOW)
        await session.commit()

        result = await make_router(session).complete(task_class=TaskClass.NORMAL, messages=MESSAGES)
        assert result.spec.provider != "google"
        assert any("kvota tugagan" in s.reason for s in result.skipped)

    async def test_quota_resets_next_minute(self, session: AsyncSession) -> None:
        spec = CATALOG["google:gemini-flash"]
        assert spec.free_rpm is not None
        quota = QuotaManager(session)
        for _ in range(spec.free_rpm):
            await quota.record_use(spec, now=FIXED_NOW)
        await session.commit()

        next_minute = FIXED_NOW + timedelta(minutes=1)
        assert await quota.has_quota(spec, now=next_minute) is True

    async def test_remaining_reports_correctly(self, session: AsyncSession) -> None:
        spec = CATALOG["groq:llama-3.3-70b"]
        quota = QuotaManager(session)
        await quota.record_use(spec, now=FIXED_NOW)
        await session.commit()

        remaining = await quota.remaining(spec, now=FIXED_NOW)
        assert spec.free_rpd is not None
        assert remaining["day"] == spec.free_rpd - 1


# ── Budjet ─────────────────────────────────────────────────────────


class TestBudget:
    async def _spend(
        self,
        session: AsyncSession,
        usd: float,
        *,
        autonomous: bool = False,
        at: datetime | None = None,
    ) -> None:
        entry = CostLedger(
            provider="anthropic",
            model="m",
            tier=ModelTier.T2_CHEAP,
            task_class=TaskClass.NORMAL,
            usd=usd,
            is_autonomous=autonomous,
        )
        if at is not None:
            entry.created_at = at
        session.add(entry)
        await session.commit()

    async def test_free_tier_never_blocked_by_budget(self, session: AsyncSession) -> None:
        await self._spend(session, 100.0)
        result = await make_router(session).complete(task_class=TaskClass.NORMAL, messages=MESSAGES)
        assert result.cost_usd == 0.0

    async def test_daily_limit_blocks_paid_model(self, session: AsyncSession) -> None:
        guard = BudgetGuard(session, make_settings())
        await self._spend(session, 0.49)
        with pytest.raises(BudgetExceededError, match="kunlik budjet"):
            await guard.check(
                estimated_usd=0.05,
                tier=ModelTier.T2_CHEAP,
                is_autonomous=False,
                now=FIXED_NOW,
            )

    async def test_run_limit_blocks(self, session: AsyncSession) -> None:
        guard = BudgetGuard(session, make_settings())
        with pytest.raises(BudgetExceededError, match="run chegarasi"):
            await guard.check(
                estimated_usd=0.05,
                tier=ModelTier.T2_CHEAP,
                is_autonomous=False,
                run_spent_usd=0.08,
                now=FIXED_NOW,
            )

    async def test_tier3_daily_call_limit(self, session: AsyncSession) -> None:
        settings = make_settings(tier3_daily_calls=2)
        guard = BudgetGuard(session, settings)
        for _ in range(2):
            session.add(
                CostLedger(
                    provider="anthropic",
                    model="claude-sonnet-5",
                    tier=ModelTier.T3_STRONG,
                    task_class=TaskClass.COMPLEX,
                    usd=0.01,
                    ok=True,
                )
            )
        await session.commit()

        with pytest.raises(BudgetExceededError, match="kuchli model kunlik chegarasi"):
            await guard.check(
                estimated_usd=0.01,
                tier=ModelTier.T3_STRONG,
                is_autonomous=False,
                now=FIXED_NOW,
            )

    async def test_autonomous_share_limited(self, session: AsyncSession) -> None:
        """Jadval vazifalari kunlik budjetning 40% idan oshmasligi kerak."""
        settings = make_settings(budget_daily_usd=1.0, autonomous_budget_share=0.4)
        guard = BudgetGuard(session, settings)
        await self._spend(session, 0.39, autonomous=True)

        with pytest.raises(BudgetExceededError, match="avtonom ulush"):
            await guard.check(
                estimated_usd=0.05,
                tier=ModelTier.T2_CHEAP,
                is_autonomous=True,
                now=FIXED_NOW,
            )

    async def test_manual_run_still_allowed_when_autonomous_exhausted(
        self, session: AsyncSession
    ) -> None:
        """Avtonom ulush tugasa ham egasi gaplasha olishi kerak."""
        settings = make_settings(budget_daily_usd=1.0, autonomous_budget_share=0.4)
        guard = BudgetGuard(session, settings)
        await self._spend(session, 0.40, autonomous=True)

        await guard.check(
            estimated_usd=0.05,
            tier=ModelTier.T2_CHEAP,
            is_autonomous=False,
            now=FIXED_NOW,
        )

    async def test_monthly_limit_blocks(self, session: AsyncSession) -> None:
        """Oy davomida yig'ilgan sarf — bugun hech narsa sarflanmagan bo'lsa ham."""
        settings = make_settings(budget_monthly_usd=1.0, budget_daily_usd=1.0, run_max_usd=1.0)
        guard = BudgetGuard(session, settings)
        await self._spend(session, 0.99, at=FIXED_NOW - timedelta(days=5))
        with pytest.raises(BudgetExceededError, match="oylik budjet"):
            await guard.check(
                estimated_usd=0.05,
                tier=ModelTier.T2_CHEAP,
                is_autonomous=False,
                now=FIXED_NOW,
            )

    async def test_snapshot_alert_threshold(self, session: AsyncSession) -> None:
        guard = BudgetGuard(session, make_settings())
        await self._spend(session, 0.41)
        snap = await guard.snapshot(now=FIXED_NOW)
        assert snap.should_alert is True
        assert snap.remaining_today_usd == pytest.approx(0.09)

    async def test_router_raises_budget_error_when_all_paid_blocked(
        self, session: AsyncSession
    ) -> None:
        """COMPLEX faqat pullik + free tier; hammasi bloklansa aniq xato beriladi."""
        providers = {
            "anthropic": FakeProvider("anthropic", ModelTier.T3_STRONG),
            "google": FakeProvider("google", ModelTier.T1_FREE, configured=False),
            "groq": FakeProvider("groq", ModelTier.T1_FREE, configured=False),
        }
        settings = make_settings(run_max_usd=0.0001)
        with pytest.raises(BudgetExceededError):
            await make_router(session, providers, settings).complete(  # type: ignore[arg-type]
                task_class=TaskClass.COMPLEX, messages=MESSAGES
            )


# ── Xarajat daftari (A-04) ─────────────────────────────────────────


class TestCostLedger:
    async def test_records_successful_call(self, session: AsyncSession) -> None:
        await make_router(session).complete(task_class=TaskClass.NORMAL, messages=MESSAGES)
        row = (await session.execute(select(CostLedger))).scalars().one()
        assert row.ok is True
        assert row.task_class is TaskClass.NORMAL
        assert row.input_tokens > 0

    async def test_records_failed_call_too(self, session: AsyncSession) -> None:
        """Xato ham daftarga tushadi — aks holda ishonchlilik ko'rinmaydi."""
        providers = all_providers(
            google=FakeProvider(
                "google", ModelTier.T1_FREE, scripted=[ProviderUnavailableError("503")]
            )
        )
        await make_router(session, providers).complete(
            task_class=TaskClass.NORMAL, messages=MESSAGES
        )
        rows = (
            (await session.execute(select(CostLedger).order_by(CostLedger.created_at)))
            .scalars()
            .all()
        )
        assert len(rows) == 2
        assert rows[0].ok is False
        assert rows[1].ok is True

    async def test_marks_autonomous_runs(self, session: AsyncSession) -> None:
        await make_router(session).complete(
            task_class=TaskClass.NORMAL, messages=MESSAGES, is_autonomous=True
        )
        row = (await session.execute(select(CostLedger))).scalars().one()
        assert row.is_autonomous is True

    async def test_total_spend_query(self, session: AsyncSession) -> None:
        router = make_router(session)
        for _ in range(3):
            await router.complete(task_class=TaskClass.NORMAL, messages=MESSAGES)
        total = (
            await session.execute(select(func.coalesce(func.sum(CostLedger.usd), 0.0)))
        ).scalar_one()
        assert total == 0.0  # free tier


# ── Baholash ───────────────────────────────────────────────────────


class TestEstimation:
    def test_estimate_is_conservative(self) -> None:
        """Chiqish tokenlari eng yomon holat (`max_tokens`) bo'yicha olinadi."""
        usage = ModelRouter.estimate_usage(
            [ChatMessage(role="user", content="a" * 400)], system="b" * 400, max_tokens=1000
        )
        assert usage.input_tokens == 200
        assert usage.output_tokens == 1000

    def test_estimate_never_zero(self) -> None:
        usage = ModelRouter.estimate_usage([], None, max_tokens=10)
        assert usage.input_tokens >= 1
