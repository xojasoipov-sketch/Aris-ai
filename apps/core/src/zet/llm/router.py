"""Model Router — ADR-0006 ning yuragi.

Vazifa sinfiga qarab nomzod modellarni ustuvorlik tartibida sinaydi:

    T0 (lokal, bepul) -> T1 (free tier) -> T2 (arzon) -> T3 (kuchli)

Nomzod quyidagi hollarda **o'tkazib yuboriladi**:
    - provayder sozlanmagan (kalit yo'q)
    - tool kerak, lekin model tool-calling'ni qo'llamaydi
    - circuit breaker ochiq (provayder ketma-ket xato bergan)
    - free tier kvotasi tugagan
    - budjet yetmaydi

Muvaffaqiyatli chaqiruvdan keyin `cost_ledger` va `quota_ledger` yangilanadi —
bu A-04 dagi metrika qaytish halqasi.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from zet.config import Settings
from zet.db.models import CostLedger
from zet.domain.enums import TaskClass
from zet.llm.base import (
    BudgetExceededError,
    ChatMessage,
    LLMProvider,
    LLMResponse,
    NoProviderAvailableError,
    ProviderConfigError,
    ProviderUnavailableError,
    RateLimitError,
    ToolSpec,
    Usage,
)
from zet.llm.budget import BudgetGuard
from zet.llm.catalog import ModelSpec, candidates_for
from zet.llm.quota import QuotaManager

log = structlog.get_logger(__name__)

_CHARS_PER_TOKEN = 4
"""Taxminiy token baholash koeffitsienti (oldindan budjet tekshiruvi uchun)."""


@dataclass
class _Breaker:
    """Bitta provayder uchun circuit breaker holati."""

    failures: int = 0
    opened_until: datetime | None = None

    def is_open(self, now: datetime) -> bool:
        return self.opened_until is not None and now < self.opened_until

    def record_failure(self, now: datetime, *, threshold: int, cooldown_s: int) -> None:
        self.failures += 1
        if self.failures >= threshold:
            self.opened_until = now + timedelta(seconds=cooldown_s)

    def record_success(self) -> None:
        self.failures = 0
        self.opened_until = None


@dataclass(frozen=True, slots=True)
class SkipReason:
    """Nomzod nega o'tkazib yuborilgani — diagnostika uchun."""

    model_key: str
    reason: str


@dataclass
class RouteResult:
    """Marshrutlash natijasi: javob + qanday yo'l bosib o'tilgani."""

    response: LLMResponse
    spec: ModelSpec
    cost_usd: float
    skipped: list[SkipReason] = field(default_factory=list)


class ModelRouter:
    """Vazifa sinfi bo'yicha eng arzon ishlaydigan modelni tanlaydi."""

    BREAKER_THRESHOLD = 3
    BREAKER_COOLDOWN_S = 120

    def __init__(
        self,
        providers: Mapping[str, LLMProvider],
        session: AsyncSession,
        settings: Settings,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._providers = providers
        self._session = session
        self._settings = settings
        self._now = now_fn or (lambda: datetime.now(UTC))
        self._quota = QuotaManager(session)
        self._budget = BudgetGuard(session, settings)
        self._breakers: dict[str, _Breaker] = {}

    # ── Yordamchi ──────────────────────────────────────────────────

    def _breaker(self, provider: str) -> _Breaker:
        return self._breakers.setdefault(provider, _Breaker())

    @staticmethod
    def estimate_usage(
        messages: Sequence[ChatMessage], system: str | None, max_tokens: int
    ) -> Usage:
        """Chaqiruvdan **oldin** budjetni tekshirish uchun taxminiy hisob.

        Aniq emas, lekin kam baholamasligi kerak — shuning uchun chiqish
        tokenlari `max_tokens` bo'yicha eng yomon holatda olinadi.
        """
        chars = len(system or "")
        for m in messages:
            chars += len(m.content)
        return Usage(
            input_tokens=max(1, chars // _CHARS_PER_TOKEN),
            output_tokens=max_tokens,
        )

    # ── Asosiy ─────────────────────────────────────────────────────

    async def complete(
        self,
        *,
        task_class: TaskClass,
        messages: Sequence[ChatMessage],
        system: str | None = None,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int = 2048,
        temperature: float = 0.0,
        run_id: UUID | None = None,
        is_autonomous: bool = False,
        run_spent_usd: float = 0.0,
        run_budget_usd: float | None = None,
    ) -> RouteResult:
        now = self._now()
        skipped: list[SkipReason] = []
        budget_blocked = False
        estimate = self.estimate_usage(messages, system, max_tokens)
        needs_vision = any(m.images for m in messages)

        for spec in candidates_for(task_class):
            provider = self._providers.get(spec.provider)

            if provider is None or not provider.is_configured:
                skipped.append(SkipReason(spec.key, "sozlanmagan"))
                continue

            if tools and not spec.supports_tools:
                skipped.append(SkipReason(spec.key, "tool-calling yo'q"))
                continue

            if needs_vision and not spec.supports_vision:
                skipped.append(SkipReason(spec.key, "vision qo'llab-quvvatlanmaydi"))
                continue

            if self._breaker(spec.provider).is_open(now):
                skipped.append(SkipReason(spec.key, "circuit breaker ochiq"))
                continue

            if not await self._quota.has_quota(spec, now=now):
                skipped.append(SkipReason(spec.key, "kvota tugagan"))
                continue

            estimated_usd = spec.cost_usd(estimate)
            try:
                await self._budget.check(
                    estimated_usd=estimated_usd,
                    tier=spec.tier,
                    is_autonomous=is_autonomous,
                    run_spent_usd=run_spent_usd,
                    run_budget_usd=run_budget_usd,
                    now=now,
                )
            except BudgetExceededError as exc:
                budget_blocked = True
                skipped.append(SkipReason(spec.key, f"budjet: {exc}"))
                continue

            started = time.perf_counter()
            try:
                response = await provider.complete(
                    model=spec.model,
                    messages=messages,
                    system=system,
                    tools=tools,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            except (RateLimitError, ProviderUnavailableError) as exc:
                self._breaker(spec.provider).record_failure(
                    now,
                    threshold=self.BREAKER_THRESHOLD,
                    cooldown_s=self.BREAKER_COOLDOWN_S,
                )
                await self._record_cost(
                    spec=spec,
                    usage=Usage(),
                    task_class=task_class,
                    run_id=run_id,
                    is_autonomous=is_autonomous,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    ok=False,
                )
                skipped.append(SkipReason(spec.key, f"xato: {type(exc).__name__}"))
                log.warning("llm.provider_failed", model=spec.key, error=str(exc))
                continue
            except ProviderConfigError as exc:
                skipped.append(SkipReason(spec.key, f"konfiguratsiya: {exc}"))
                continue

            actual_usd = spec.cost_usd(response.usage)
            await self._quota.record_use(spec, now=now)
            await self._record_cost(
                spec=spec,
                usage=response.usage,
                task_class=task_class,
                run_id=run_id,
                is_autonomous=is_autonomous,
                latency_ms=response.latency_ms,
                ok=True,
            )
            self._breaker(spec.provider).record_success()

            log.info(
                "llm.routed",
                model=spec.key,
                tier=spec.tier.value,
                task_class=task_class.value,
                usd=round(actual_usd, 6),
                skipped=len(skipped),
            )
            return RouteResult(response=response, spec=spec, cost_usd=actual_usd, skipped=skipped)

        detail = "; ".join(f"{s.model_key}: {s.reason}" for s in skipped) or "nomzod yo'q"
        if budget_blocked:
            raise BudgetExceededError(f"{task_class.value} uchun budjet yetmadi — {detail}")
        raise NoProviderAvailableError(f"{task_class.value} uchun provayder topilmadi — {detail}")

    async def _record_cost(
        self,
        *,
        spec: ModelSpec,
        usage: Usage,
        task_class: TaskClass,
        run_id: UUID | None,
        is_autonomous: bool,
        latency_ms: int,
        ok: bool,
    ) -> None:
        """A-04: har bir chaqiruv daftarga tushadi (xato bo'lsa ham)."""
        self._session.add(
            CostLedger(
                run_id=run_id,
                provider=spec.provider,
                model=spec.model,
                tier=spec.tier,
                task_class=task_class,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                usd=spec.cost_usd(usage),
                latency_ms=latency_ms,
                ok=ok,
                is_autonomous=is_autonomous,
            )
        )
        await self._session.flush()


async def mark_run_verified(
    session_factory: object,
    run_id: UUID,
    *,
    verified_ok: bool,
) -> None:
    """A-04 feedback loop: run yakunida shu run'ning barcha CostLedger
    yozuvlaridagi `verified_ok`ni belgilaydi.

    Ilgari `verified_ok` qonundan-so'ng NULL bo'lib qolardi va Router
    "modeldan olingan javob TO'G'RI edimi" ma'lumotini hech qachon
    o'rganmasdi — ADR-0006 va A-04'ning butun ma'nosi shu edi. Endi
    Orchestrator har run yakunida chaqiradi.

    Fail-open — DB xatosi run natijasini o'zgartirmaydi."""
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from zet.db.session import session_scope

    factory: async_sessionmaker[AsyncSession] = session_factory  # type: ignore[assignment]
    try:
        async with session_scope(factory) as session:
            await session.execute(
                update(CostLedger)
                .where(CostLedger.run_id == run_id)
                .values(verified_ok=verified_ok)
            )
    except Exception:
        log.warning("router.mark_verified_failed", run_id=str(run_id))
