"""Jonli manba testlari (Z50).

NEGA BU TESTLAR BOR.

Ega NEXUS mockupini ko'rsatib, kartalar HAQIQIY bo'lishini talab
qildi: «men o'yinchoq emas, haqiqiy ishlaydigan tizim yasayapman».

Shuning uchun eng muhim invariant — **soxta qiymat hech qachon
qaytmaydi**. Manba yiqilsa, karta bo'sh qoladi va sababi yoziladi;
o'ylab topilgan harorat yoki narx ko'rsatilmaydi.

Ikkinchi invariant — **qisman muvaffaqiyat**. Beshta manbadan
bittasi o'chsa, qolgan to'rttasi baribir ko'rinadi. Aks holda bitta
RSS saytining nosozligi butun ekranni bo'shatib qo'yardi.

Tarmoq CHAQIRILMAYDI: barcha HTTP javoblar o'rnini bosuvchi bilan
beriladi — testlar internetsiz ham, tashqi xizmat o'chganda ham
bir xil ishlaydi.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from zet.feeds import providers
from zet.feeds.providers import (
    FeedError,
    clear_cache,
    fetch_news,
    fetch_quote,
    fetch_quotes,
    fetch_rates,
    fetch_sports,
    fetch_weather,
)

WEATHER_JSON: dict[str, Any] = {
    "current": {
        "temperature_2m": 34.2,
        "weather_code": 0,
        "relative_humidity_2m": 21,
        "time": "2026-08-13T10:00",
    },
    "daily": {"temperature_2m_max": [39.1], "temperature_2m_min": [23.4]},
}
QUOTE_JSON: dict[str, Any] = {
    "chart": {
        "result": [
            {
                "meta": {
                    "regularMarketPrice": 224.09,
                    "chartPreviousClose": 211.0,
                    "shortName": "NVIDIA Corporation",
                    "currency": "USD",
                },
                "indicators": {"quote": [{"close": [210.0, None, 218.5, 224.09]}]},
            }
        ]
    }
}
RSS_XML = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Birinchi xabar</title><link>https://x.uz/1</link><pubDate>Wed, 13 Aug 2026</pubDate></item>
<item><title>Ikkinchi xabar</title><link>https://x.uz/2</link></item>
<item><title>   </title><link>https://x.uz/3</link></item>
</channel></rss>"""


@pytest.fixture(autouse=True)
def _clean() -> None:
    """Kesh testlar orasida oqib o'tmasin."""
    clear_cache()


def _mock(monkeypatch: pytest.MonkeyPatch, payload: Any, *, text: str = "") -> list[str]:
    """`_get` o'rniga qo'yiladi; chaqirilgan URL'larni yozib boradi."""
    calls: list[str] = []

    async def fake_get(url: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
        calls.append(url)
        if text:
            return httpx.Response(200, text=text)
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(providers, "_get", fake_get)
    return calls


def _fail(monkeypatch: pytest.MonkeyPatch, message: str = "Manbaga ulanib bo'lmadi") -> None:
    async def fake_get(url: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
        raise FeedError(message)

    monkeypatch.setattr(providers, "_get", fake_get)


class TestWeather:
    async def test_reads_real_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock(monkeypatch, WEATHER_JSON)

        result = await fetch_weather(latitude=41.3, longitude=69.2, timezone="Asia/Tashkent")

        assert result["temperature_c"] == 34
        assert result["high_c"] == 39
        assert result["low_c"] == 23
        assert result["condition"] == "Ochiq"

    async def test_unknown_weather_code_is_a_dash_not_a_guess(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Noma'lum kod uchun eng yaqin holat TAXMIN QILINMAYDI."""
        _mock(
            monkeypatch,
            {**WEATHER_JSON, "current": {**WEATHER_JSON["current"], "weather_code": 77}},
        )

        result = await fetch_weather(latitude=41.3, longitude=69.2, timezone="UTC")

        assert result["condition"] == "—"

    async def test_broken_payload_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock(monkeypatch, {"current": {}})

        with pytest.raises(FeedError):
            await fetch_weather(latitude=41.3, longitude=69.2, timezone="UTC")

    async def test_cache_prevents_a_second_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Interfeys har 30 soniyada so'raydi — bepul manba bloklanmasin."""
        calls = _mock(monkeypatch, WEATHER_JSON)

        await fetch_weather(latitude=41.3, longitude=69.2, timezone="UTC")
        second = await fetch_weather(latitude=41.3, longitude=69.2, timezone="UTC")

        assert len(calls) == 1
        assert second["age_s"] >= 0


class TestStocks:
    async def test_price_and_change_are_computed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock(monkeypatch, QUOTE_JSON)

        result = await fetch_quote("nvda")

        assert result["symbol"] == "NVDA"
        assert result["price"] == 224.09
        assert result["change"] == 13.09
        assert result["change_percent"] == pytest.approx(6.2, abs=0.1)

    async def test_missing_days_do_not_break_the_sparkline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bayram kuni `None` keladi — chiziq uzilmasligi kerak."""
        _mock(monkeypatch, QUOTE_JSON)

        result = await fetch_quote("NVDA")

        assert None not in result["spark"]
        assert len(result["spark"]) == 3

    async def test_empty_symbol_is_refused(self) -> None:
        with pytest.raises(FeedError):
            await fetch_quote("   ")

    async def test_one_bad_symbol_does_not_lose_the_others(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bitta noto'g'ri belgi butun kartani o'chirmasligi kerak."""
        calls: list[str] = []

        async def fake_get(url: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
            calls.append(url)
            if "BADSYM" in url:
                raise FeedError("404")
            return httpx.Response(200, json=QUOTE_JSON)

        monkeypatch.setattr(providers, "_get", fake_get)

        result = await fetch_quotes(["NVDA", "BADSYM"])

        assert len(result) == 1

    async def test_all_failing_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fail(monkeypatch)

        with pytest.raises(FeedError):
            await fetch_quotes(["NVDA", "AAPL"])


class TestNews:
    async def test_headlines_are_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock(monkeypatch, None, text=RSS_XML)

        items = await fetch_news("https://x.uz/rss")

        assert [i["title"] for i in items] == ["Birinchi xabar", "Ikkinchi xabar"]

    async def test_broken_xml_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock(monkeypatch, None, text="<rss><channel>")

        with pytest.raises(FeedError):
            await fetch_news("https://x.uz/rss")

    async def test_empty_feed_raises_instead_of_returning_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bo'sh ro'yxat "yangilik yo'q" degan YOLG'ON taassurot berardi."""
        _mock(monkeypatch, None, text='<?xml version="1.0"?><rss><channel></channel></rss>')

        with pytest.raises(FeedError):
            await fetch_news("https://x.uz/rss")


class TestSports:
    async def test_cancelled_match_shows_a_dash_not_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """0:0 — HAQIQIY natija. Hisobi yo'q o'yin uni ko'rsatmasligi kerak."""
        _mock(
            monkeypatch,
            {
                "events": [
                    {
                        "strHomeTeam": "Bunyodkor",
                        "strAwayTeam": "Pakhtakor",
                        "intHomeScore": None,
                        "intAwayScore": None,
                    }
                ]
            },
        )

        result = await fetch_sports("4328")

        assert result[0]["home_score"] == "—"

    async def test_no_events_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock(monkeypatch, {"events": []})

        with pytest.raises(FeedError):
            await fetch_sports("4328")


class TestRates:
    async def test_only_requested_currencies_return(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock(
            monkeypatch,
            [
                {"Ccy": "USD", "CcyNm_UZ": "AQSH dollari", "Rate": "11949.5", "Diff": "12.3"},
                {"Ccy": "EUR", "CcyNm_UZ": "Yevro", "Rate": "13793.1", "Diff": "-4.0"},
                {"Ccy": "JPY", "CcyNm_UZ": "Iyena", "Rate": "80.1", "Diff": "0"},
            ],
        )

        result = await fetch_rates(["usd", "EUR"])

        assert {r["code"] for r in result} == {"USD", "EUR"}
        assert result[0]["rate"] == pytest.approx(11949.5)

    async def test_unknown_currency_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock(monkeypatch, [{"Ccy": "USD", "Rate": "11949", "Diff": "0"}])

        with pytest.raises(FeedError):
            await fetch_rates(["XYZ"])
