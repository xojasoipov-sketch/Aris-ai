"""`PublicAPIAdapter` — bitta bazaviy klass, HAR BIR konkret adapter
faqat `_call_provider()`ni implement qiladi (Bo'lim 6/7).

MUHIM: bu klass `zet.tools.base.Tool`ning O'ZI — YANGI abstraksiya
QURILMAYDI. `Tool.execute()` (base.py) ALLAQACHON quyidagilarni
qiladi, bu klass ularni QAYTA YOZMAYDI:
    - `asyncio.wait_for(timeout=self.timeout_s)` — umumiy timeout
    - `ToolError` → `ToolResult(success=False, ...)`, `ToolQuotaError`
      uchun `retryable=False`
    - kutilmagan istisno → xavfsiz "Kutilmagan xato" natija

Bu klass FAQAT o'z ustiga oladigan narsa (HTTP darajasida, `_execute()`
ichida):
    1. Vaqtinchalik tarmoq xatolarini (ulanish, 5xx) `tenacity` bilan
       QISQA qayta urinish — `pyproject.toml`da ALLAQACHON bor
       bog'liqlik, ILGARI HECH QAYERDA ishlatilmagan edi.
    2. HTTP javobini `zet.core.failure_classification`ning MAVJUD
       sinflariga to'g'ri xaritalanadigan `ToolError` turlariga
       o'girish (429 → `ToolQuotaError`, timeout → `ToolTimeoutError`,
       aks holda `ToolError`) — YANGI xato taksonomiyasi QURILMAYDI.
    3. Har bir chaqiruvni `ProviderHealthTracker`ga yozish (muvaffaqiyat/
       muvaffaqiyatsizlik/kechikish) — ixtiyoriy, berilmasa passiv.

QATTIQ SHARTNOMA — `_call_provider()` uchun (Bo'lim 11): agar provayder
HTTP 200 bilan javob bersa-yu, javob TANASIDA xato belgisi bo'lsa
(masalan `{"error": true}`), `_call_provider()`ning O'ZI shu yerda
`ToolError` OTISHI SHART — HTTP status kodi yetarli emas, chaqiruvchi
`_execute()` buni "muvaffaqiyat" deb noto'g'ri belgilamasligi kerak.
"""

from __future__ import annotations

import time
from abc import abstractmethod
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

from zet.domain.enums import PermissionLevel, TrustLevel
from zet.integrations.public_apis.health.scoring import ProviderHealthTracker
from zet.tools.base import Tool, ToolError, ToolQuotaError, ToolTimeoutError

log = structlog.get_logger(__name__)

MAX_ATTEMPTS = 2
"""Vaqtinchalik xato — jami shuncha urinish (1 asosiy + 1 qayta).
Ko'proq emas: `RecoveryEngine` allaqachon QADAM darajasida qayta
urinadi (LLM-diagnoz bilan) — bu yerdagi qayta urinish faqat TEZ,
LOKAL tarmoq shovqinini qoplaydi, sekin diagnostika o'rniga emas."""


def _is_transient(exc: BaseException) -> bool:
    """Qayta urinishga arziydigan xato turlarini aniqlaydi.

    Ulanish/o'qish xatolari va 5xx — odatda VAQTINCHALIK. 4xx (429
    bundan mustasno — u alohida `ToolQuotaError`ga aylanadi, qayta
    urinilmaydi) — DETERMINISTIK, qayta urinish yordam bermaydi.
    """
    if isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout | httpx.ReadTimeout):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


class PublicAPIAdapter(Tool):
    """Tashqi (public-apis katalogidan topilgan) API uchun `Tool` adapteri.

    Barcha hozirgi konkret adapterlar O'QISH-FAQAT lookup'lar — shuning
    uchun `permission_level`/`idempotent` default'lari shunga mos
    (subclass kerak bo'lsa override qiladi)."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        health_tracker: ProviderHealthTracker | None = None,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._health = health_tracker

    @property
    def provider_name(self) -> str:
        """Sog'liq kuzatuvi/xato xabarlarida ishlatiladigan qisqa nom.

        Default — tool nomi; subclass aniqroq nom bersa (masalan
        haqiqiy provayder domeni) override qilishi mumkin.
        """
        return self.name

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    @property
    def output_trust_level(self) -> TrustLevel:
        # Tashqi manba — natija BUYRUQ emas, MA'LUMOT (A-05).
        return TrustLevel.UNTRUSTED

    @property
    def idempotent(self) -> bool:
        return True

    @property
    def timeout_s(self) -> int:
        return 15

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=float(self.timeout_s))
        return self._client

    async def aclose(self) -> None:
        """Ichki HTTP klientni yopadi (agar o'zi yaratgan bo'lsa)."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    @abstractmethod
    async def _call_provider(self, params: dict[str, Any]) -> dict[str, Any]:
        """Haqiqiy provayder API'siga so'rov — konkret adapter yozadi.

        Shartnoma: muvaffaqiyatsizlikni HAR DOIM istisno bilan
        bildiradi (`httpx.HTTPStatusError`/boshqa `httpx.HTTPError`
        yoki, agar HTTP 200 bo'lsa-yu javob TANASI xato bo'lsa,
        to'g'ridan-to'g'ri `zet.tools.base.ToolError`) — hech qachon
        "muvaffaqiyat" natija ICHIDA xato belgisi bilan qaytmaydi.
        """

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        t0 = time.monotonic()
        retryer = AsyncRetrying(
            stop=stop_after_attempt(MAX_ATTEMPTS),
            wait=wait_exponential(multiplier=0.4, max=2.0),
            retry=retry_if_exception(_is_transient),
            reraise=True,
        )
        try:
            result: dict[str, Any] = await retryer(self._call_provider, params)
        except httpx.HTTPStatusError as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            status = exc.response.status_code
            if status == 429:
                self._record_failure(latency_ms, rate_limited=True)
                msg = f"{self.provider_name}: kvota/so'rov chegarasi tugadi (HTTP 429)"
                raise ToolQuotaError(msg) from exc
            self._record_failure(latency_ms)
            msg = f"{self.provider_name}: HTTP {status}"
            raise ToolError(msg) from exc
        except httpx.TimeoutException as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            self._record_failure(latency_ms, timeout=True)
            msg = f"{self.provider_name}: javob vaqti tugadi"
            raise ToolTimeoutError(msg) from exc
        except httpx.HTTPError as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            self._record_failure(latency_ms)
            msg = f"{self.provider_name}: tarmoq xatosi: {exc}"
            raise ToolError(msg) from exc

        latency_ms = (time.monotonic() - t0) * 1000
        self._record_success(latency_ms)
        return result

    def _record_success(self, latency_ms: float) -> None:
        if self._health is not None:
            self._health.record_success(
                self.provider_name, latency_ms=latency_ms, now=datetime.now(UTC)
            )

    def _record_failure(
        self, latency_ms: float, *, rate_limited: bool = False, timeout: bool = False
    ) -> None:
        if self._health is not None:
            self._health.record_failure(
                self.provider_name,
                latency_ms=latency_ms,
                now=datetime.now(UTC),
                rate_limited=rate_limited,
                timeout=timeout,
            )


__all__ = ["PublicAPIAdapter"]
