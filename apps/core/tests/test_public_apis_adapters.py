"""public-apis adapter qatlami testlari (JB-18, Bo'lim 6/7/11/12/13) —
`PublicAPIAdapter` bazaviy retry/xato-xaritalash mantiqi + 3 haqiqiy
keyless adapter (`location.geocode`, `location.reverse_geocode`,
`ip.lookup`), barchasi `respx` bilan (HAQIQIY tarmoqqa chiqmasdan,
`test_telegram_tools.py` bilan bir xil naqsh).
"""

from __future__ import annotations

from typing import Any

import httpx
import respx

from zet.domain.enums import PermissionLevel, RiskLevel, TrustLevel
from zet.integrations.public_apis.adapters.base import MAX_ATTEMPTS, PublicAPIAdapter
from zet.integrations.public_apis.adapters.geocode import (
    GeocodeForwardTool,
    GeocodeReverseTool,
)
from zet.integrations.public_apis.adapters.ip_lookup import IpLookupTool
from zet.integrations.public_apis.health.scoring import ProviderHealthTracker

_URL = "https://fake-provider.example/v1/lookup"


class _FakeAdapter(PublicAPIAdapter):
    """`PublicAPIAdapter`ning minimal konkret nasli — faqat bazaviy
    retry/xato xaritalash mantiqini o'z holicha (haqiqiy adapterlarning
    domen-xos parse mantig'idan ajratib) sinash uchun."""

    @property
    def name(self) -> str:
        return "test.fake_adapter"

    @property
    def description(self) -> str:
        return "test uchun soxta adapter"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def _call_provider(self, params: dict[str, Any]) -> dict[str, Any]:
        response = await self._get_client().get(_URL)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data


# ── Default kontrakt xususiyatlari ─────────────────────────────────


class TestPublicAPIAdapterDefaults:
    def test_permission_read_trust_untrusted_idempotent(self) -> None:
        tool = _FakeAdapter()
        assert tool.permission_level == PermissionLevel.READ
        assert tool.output_trust_level == TrustLevel.UNTRUSTED
        assert tool.idempotent is True
        assert tool.timeout_s == 15

    def test_risk_level_defaults_low_for_unlisted_tool(self) -> None:
        # `TOOL_RISK_LEVELS`da yo'q tool nomi — LOW fallback (`risk_for`).
        assert _FakeAdapter().risk_level == RiskLevel.LOW

    def test_provider_name_defaults_to_tool_name(self) -> None:
        assert _FakeAdapter().provider_name == "test.fake_adapter"


# ── Muvaffaqiyat + sog'liq yozuvi ───────────────────────────────────


class TestPublicAPIAdapterSuccess:
    @respx.mock
    async def test_success_records_health_and_returns_result(self) -> None:
        respx.get(_URL).mock(return_value=httpx.Response(200, json={"ok": True, "value": 42}))
        tracker = ProviderHealthTracker()
        tool = _FakeAdapter(health_tracker=tracker)

        result = await tool.execute({})
        assert result.success is True
        assert result.output == {"ok": True, "value": 42}
        assert result.trust_level == TrustLevel.UNTRUSTED

        snap = tracker.snapshot("test.fake_adapter")
        assert snap is not None
        assert snap.total_calls == 1
        assert snap.successes == 1
        assert snap.failures == 0

    @respx.mock
    async def test_no_health_tracker_does_not_crash(self) -> None:
        respx.get(_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
        tool = _FakeAdapter()  # health_tracker=None
        result = await tool.execute({})
        assert result.success is True


# ── 429 → ToolQuotaError, retryable=False, retry QILINMAYDI ────────


class TestRateLimitMapsToQuotaError:
    @respx.mock
    async def test_429_maps_to_quota_error_no_retry(self) -> None:
        route = respx.get(_URL).mock(return_value=httpx.Response(429, json={"error": "rate limited"}))
        tracker = ProviderHealthTracker()
        tool = _FakeAdapter(health_tracker=tracker)

        result = await tool.execute({})
        assert result.success is False
        assert result.retryable is False  # ToolQuotaError — Executor qayta urinmasin
        assert "kvota" in (result.error or "").lower() or "429" in (result.error or "")
        assert route.call_count == 1  # 429 — DETERMINISTIK, qayta urinilmadi

        snap = tracker.snapshot("test.fake_adapter")
        assert snap is not None
        assert snap.rate_limited == 1
        assert snap.failures == 1


# ── Boshqa 4xx → ToolError, retry QILINMAYDI ────────────────────────


class TestOther4xxMapsToToolErrorNoRetry:
    @respx.mock
    async def test_404_maps_to_generic_tool_error_single_attempt(self) -> None:
        route = respx.get(_URL).mock(return_value=httpx.Response(404))
        tool = _FakeAdapter()
        result = await tool.execute({})
        assert result.success is False
        assert result.retryable is True  # oddiy ToolError — Executor xohlasa qayta urinishi mumkin
        assert route.call_count == 1


# ── 5xx → vaqtinchalik, RETRY QILINADI ──────────────────────────────


class TestServerErrorRetries:
    @respx.mock
    async def test_persistent_500_retries_up_to_max_attempts_then_fails(self) -> None:
        route = respx.get(_URL).mock(return_value=httpx.Response(500))
        tool = _FakeAdapter()
        result = await tool.execute({})
        assert result.success is False
        assert route.call_count == MAX_ATTEMPTS  # 1 asosiy + 1 qayta urinish

    @respx.mock
    async def test_transient_500_then_success_recovers(self) -> None:
        route = respx.get(_URL).mock(
            side_effect=[httpx.Response(500), httpx.Response(200, json={"recovered": True})]
        )
        tool = _FakeAdapter()
        result = await tool.execute({})
        assert result.success is True
        assert result.output == {"recovered": True}
        assert route.call_count == 2


# ── Timeout → ToolTimeoutError ──────────────────────────────────────


class TestTimeoutMapsToTimeoutError:
    @respx.mock
    async def test_persistent_timeout_maps_to_timeout_error(self) -> None:
        respx.get(_URL).mock(side_effect=httpx.ReadTimeout("slow"))
        tracker = ProviderHealthTracker()
        tool = _FakeAdapter(health_tracker=tracker)
        result = await tool.execute({})
        assert result.success is False
        assert "vaqti tugadi" in (result.error or "")

        snap = tracker.snapshot("test.fake_adapter")
        assert snap is not None
        assert snap.timeouts == 1


# ── Connect error → vaqtinchalik, retry, keyin ToolError ───────────


class TestConnectErrorRetriesThenToolError:
    @respx.mock
    async def test_persistent_connect_error_retries_then_fails(self) -> None:
        route = respx.get(_URL).mock(side_effect=httpx.ConnectError("dns failure"))
        tool = _FakeAdapter()
        result = await tool.execute({})
        assert result.success is False
        assert route.call_count == MAX_ATTEMPTS


# ── aclose() — faqat o'zi yaratgan klientni yopadi ──────────────────


class TestAcloseOwnership:
    async def test_owns_client_by_default_and_closes(self) -> None:
        tool = _FakeAdapter()
        assert tool._owns_client is True
        client = tool._get_client()
        assert client.is_closed is False
        await tool.aclose()
        assert client.is_closed is True

    async def test_external_client_not_closed_by_aclose(self) -> None:
        external = httpx.AsyncClient()
        tool = _FakeAdapter(client=external)
        assert tool._owns_client is False
        await tool.aclose()
        assert external.is_closed is False
        await external.aclose()


# ── GeocodeForwardTool (location.geocode) ───────────────────────────


class TestGeocodeForwardTool:
    def test_permission_and_name(self) -> None:
        tool = GeocodeForwardTool()
        assert tool.name == "location.geocode"
        assert tool.permission_level == PermissionLevel.READ
        assert tool.risk_level == RiskLevel.LOW

    @respx.mock
    async def test_successful_geocode_maps_fields(self) -> None:
        respx.get("https://geocoding-api.open-meteo.com/v1/search").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "name": "Tashkent",
                            "country": "Uzbekistan",
                            "admin1": "Tashkent",
                            "latitude": 41.26465,
                            "longitude": 69.21627,
                            "population": 2571668,
                            "timezone": "Asia/Tashkent",
                        }
                    ]
                },
            )
        )
        tool = GeocodeForwardTool()
        result = await tool.execute({"query": "Tashkent"})
        assert result.success is True
        assert result.output["total_found"] == 1
        assert result.output["results"][0]["name"] == "Tashkent"
        assert result.output["results"][0]["latitude"] == 41.26465

    @respx.mock
    async def test_no_results_key_absent_does_not_crash(self) -> None:
        """Bo'lim 11: HTTP 200 lekin `results` KALITI UMUMAN yo'q — bu
        SUCCESS "topilmadi", YOLG'ON emas — KeyError bermasligi shart."""
        respx.get("https://geocoding-api.open-meteo.com/v1/search").mock(
            return_value=httpx.Response(200, json={"generationtime_ms": 0.1})
        )
        tool = GeocodeForwardTool()
        result = await tool.execute({"query": "Nonexistent Place Xyz"})
        assert result.success is True
        assert result.output["total_found"] == 0
        assert result.output["results"] == []

    @respx.mock
    async def test_provider_5xx_maps_to_failed_tool_result(self) -> None:
        respx.get("https://geocoding-api.open-meteo.com/v1/search").mock(
            return_value=httpx.Response(503)
        )
        tool = GeocodeForwardTool()
        result = await tool.execute({"query": "Tashkent"})
        assert result.success is False


class TestGeocodeReverseTool:
    def test_name(self) -> None:
        assert GeocodeReverseTool().name == "location.reverse_geocode"

    @respx.mock
    async def test_successful_reverse_geocode_maps_fields(self) -> None:
        respx.get("https://api.bigdatacloud.net/data/reverse-geocode-client").mock(
            return_value=httpx.Response(
                200,
                json={
                    "city": "Tashkent",
                    "locality": "Tashkent",
                    "countryName": "Uzbekistan",
                    "countryCode": "UZ",
                    "principalSubdivision": "Tashkent",
                    "continent": "Asia",
                },
            )
        )
        tool = GeocodeReverseTool()
        result = await tool.execute({"latitude": 41.26, "longitude": 69.21})
        assert result.success is True
        assert result.output["city"] == "Tashkent"
        assert result.output["country_code"] == "UZ"


# ── IpLookupTool (ip.lookup) ─────────────────────────────────────────


class TestIpLookupTool:
    def test_name(self) -> None:
        assert IpLookupTool().name == "ip.lookup"

    async def test_invalid_ip_raises_validation_error_without_network_call(self) -> None:
        """Bo'lim 10: noto'g'ri format — TARMOQQA chiqmasdan oldin rad
        etiladi (behuda tashqi so'rov yubormaslik uchun)."""
        with respx.mock:
            # Hech qanday route ro'yxatga OLINMAGAN — chaqirilsa respx
            # o'zi xato beradi (tarmoqqa chiqishga urinilgani isboti).
            tool = IpLookupTool()
            result = await tool.execute({"ip": "not-an-ip-address"})
        assert result.success is False
        assert "haqiqiy IP" in (result.error or "")

    @respx.mock
    async def test_successful_lookup_maps_fields(self) -> None:
        respx.get("https://ipwho.is/8.8.8.8").mock(
            return_value=httpx.Response(
                200,
                json={
                    "ip": "8.8.8.8",
                    "success": True,
                    "city": "Mountain View",
                    "region": "California",
                    "country": "United States",
                    "country_code": "US",
                    "latitude": 37.4056,
                    "longitude": -122.0775,
                    "connection": {"isp": "Google LLC"},
                    "timezone": {"id": "America/Los_Angeles"},
                },
            )
        )
        tool = IpLookupTool()
        result = await tool.execute({"ip": "8.8.8.8"})
        assert result.success is True
        assert result.output["city"] == "Mountain View"
        assert result.output["isp"] == "Google LLC"
        assert result.output["timezone"] == "America/Los_Angeles"

    @respx.mock
    async def test_http_200_but_body_success_false_raises_tool_error(self) -> None:
        """Bo'lim 11 QATTIQ SHARTNOMA: HTTP 200 YETARLI EMAS — javob
        tanasidagi `success: false` o'zi xato sifatida ko'tarilishi shart."""
        respx.get("https://ipwho.is/1.2.3.4").mock(
            return_value=httpx.Response(
                200, json={"success": False, "message": "reserved range"}
            )
        )
        tool = IpLookupTool()
        result = await tool.execute({"ip": "1.2.3.4"})
        assert result.success is False
        assert "reserved range" in (result.error or "")

    @respx.mock
    async def test_ipv6_accepted(self) -> None:
        respx.get("https://ipwho.is/2001:4860:4860::8888").mock(
            return_value=httpx.Response(200, json={"success": True, "ip": "2001:4860:4860::8888"})
        )
        tool = IpLookupTool()
        result = await tool.execute({"ip": "2001:4860:4860::8888"})
        assert result.success is True
