"""Tashqi jonli manbalar — ob-havo, aksiya, yangilik, sport (Z50).

NEGA BU MODUL KERAK BO'LDI.

Ega yuborgan NEXUS mockupida o'nta karta bor: MUSIC, NEWS, INSTAGRAM,
STOCKS, AI, PROJECTS, CALENDAR, WEATHER, SPORTS, SYSTEM. Ularning
yarmi ortida ZET'da hech qanday manba yo'q edi.

Ega qarori aniq: **"men o'yinchoq emas, haqiqiy ishlaydigan tizim
yasayapman"** — ya'ni kartalarga son o'ylab topib qo'yish mumkin emas.
Shu sabab har bir karta HAQIQIY manbaga ulanadi.

MANBA TANLOVI — KALIT TALAB QILMAYDIGANLARI BIRINCHI. Ega allaqachon
o'nlab API kalitini boshqarayapti; yana to'rttasini qo'shish har bir
kartani "sozlanmagan" holatda qoldirish xavfini oshiradi. Shuning
uchun:

    Ob-havo   — Open-Meteo      kalitsiz
    Aksiya    — Yahoo Finance   kalitsiz
    Yangilik  — RSS (Gazeta.uz) kalitsiz
    Sport     — TheSportsDB     ochiq sinov kaliti

SOXTA MA'LUMOT QAYTARILMAYDI. Manba javob bermasa `FeedError` otiladi
va interfeys "manba javob bermadi" deb ochiq ko'rsatadi. Oxirgi
ma'lum qiymatni "hozirgi" deb ko'rsatish ham yolg'on bo'lardi —
shuning uchun kesh qiymati YOSHI bilan birga qaytadi.

KESH NEGA KERAK. Interfeys kartalarni har 30-60 soniyada yangilaydi.
Keshsiz bu tashqi xizmatlarga daqiqada o'nlab so'rov degani — bepul
qatlamlar buni bloklaydi. TTL har manbaning O'ZGARISH TEZLIGIDAN
kelib chiqadi: ob-havo 10 daqiqa, birja 1 daqiqa, yangilik 15 daqiqa.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Final

import httpx
import structlog
from defusedxml import ElementTree

log = structlog.get_logger(__name__)

TIMEOUT_S: Final = 12.0
USER_AGENT: Final = "ZET/1.0 (personal assistant)"


class FeedError(RuntimeError):
    """Tashqi manba javob bermadi yoki javobi tushunarsiz."""


# ── Kesh ──────────────────────────────────────────────────────────


@dataclass
class _Entry:
    value: Any
    stored_at: float


@dataclass
class TTLCache:
    """Oddiy TTL kesh — jarayon xotirasida.

    Redis ATAYIN ishlatilmadi: bu ma'lumot arzon, qayta olinadi va
    yo'qolsa hech narsa buzilmaydi. Yana bitta tashqi bog'liqlik
    qo'shish foydadan ko'ra ko'proq nosozlik yo'li ochardi.
    """

    _data: dict[str, _Entry] = field(default_factory=dict)

    def get(self, key: str, ttl_s: float) -> tuple[Any, float] | None:
        """(qiymat, yoshi) yoki `None`. Yosh — soniyada."""
        entry = self._data.get(key)
        if entry is None:
            return None
        age = time.monotonic() - entry.stored_at
        if age > ttl_s:
            return None
        return entry.value, age

    def put(self, key: str, value: Any) -> None:
        self._data[key] = _Entry(value=value, stored_at=time.monotonic())

    def clear(self) -> None:
        self._data.clear()


_cache = TTLCache()


def clear_cache() -> None:
    """Testlar uchun — keshni tozalaydi."""
    _cache.clear()


async def _get(url: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
    """HTTP GET — xato bo'lsa `FeedError`."""
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_S,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise FeedError(f"Manba {exc.response.status_code} qaytardi") from exc
    except httpx.HTTPError as exc:
        raise FeedError(f"Manbaga ulanib bo'lmadi: {type(exc).__name__}") from exc
    else:
        return response


# ── Ob-havo (Open-Meteo, kalitsiz) ────────────────────────────────

WEATHER_TTL_S: Final = 600.0

# WMO ob-havo kodlari → o'zbekcha. To'liq jadval ATAYIN emas: kamdan
# kam uchraydigan kodlar (masalan 96 — do'l bilan momaqaldiroq) eng
# yaqin umumiy tavsifga yig'ilgan, chunki kartada bitta qator joy bor.
_WMO: Final[dict[int, str]] = {
    0: "Ochiq",
    1: "Asosan ochiq",
    2: "Bulutli",
    3: "To'liq bulutli",
    45: "Tuman",
    48: "Qirovli tuman",
    51: "Mayda yomg'ir",
    53: "Yomg'ir",
    55: "Kuchli yomg'ir",
    61: "Yomg'ir",
    63: "Yomg'ir",
    65: "Kuchli yomg'ir",
    71: "Qor",
    73: "Qor",
    75: "Kuchli qor",
    80: "Jala",
    81: "Jala",
    82: "Kuchli jala",
    95: "Momaqaldiroq",
    96: "Momaqaldiroq",
    99: "Momaqaldiroq",
}


async def fetch_weather(*, latitude: float, longitude: float, timezone: str) -> dict[str, Any]:
    """Hozirgi ob-havo va bugungi eng yuqori/past harorat."""
    key = f"weather:{latitude:.3f}:{longitude:.3f}"
    cached = _cache.get(key, WEATHER_TTL_S)
    if cached is not None:
        value, age = cached
        return {**value, "age_s": round(age)}

    response = await _get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,weather_code,relative_humidity_2m",
            "daily": "temperature_2m_max,temperature_2m_min",
            "timezone": timezone,
            "forecast_days": 1,
        },
    )
    try:
        raw = response.json()
        current = raw["current"]
        daily = raw["daily"]
        value = {
            "temperature_c": round(float(current["temperature_2m"])),
            "humidity_percent": round(float(current["relative_humidity_2m"])),
            "condition": _WMO.get(int(current["weather_code"]), "—"),
            "high_c": round(float(daily["temperature_2m_max"][0])),
            "low_c": round(float(daily["temperature_2m_min"][0])),
            "observed_at": str(current["time"]),
        }
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise FeedError("Ob-havo javobi tushunarsiz") from exc

    _cache.put(key, value)
    return {**value, "age_s": 0}


# ── Aksiya (Yahoo Finance, kalitsiz) ──────────────────────────────

STOCKS_TTL_S: Final = 60.0


async def fetch_quote(symbol: str) -> dict[str, Any]:
    """Bitta aksiya narxi, o'zgarishi va 5 kunlik sparkline."""
    symbol = symbol.strip().upper()
    if not symbol:
        raise FeedError("Aksiya belgisi bo'sh")

    key = f"quote:{symbol}"
    cached = _cache.get(key, STOCKS_TTL_S)
    if cached is not None:
        value, age = cached
        return {**value, "age_s": round(age)}

    response = await _get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        params={"interval": "1d", "range": "1mo"},
    )
    try:
        result = response.json()["chart"]["result"][0]
        meta = result["meta"]
        price = float(meta["regularMarketPrice"])
        previous = float(meta.get("chartPreviousClose") or meta.get("previousClose") or price)

        # `None` — savdo bo'lmagan kun (bayram). Ularni tashlab
        # yubormasak sparkline uzilib qolardi.
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]

        change = price - previous
        value = {
            "symbol": symbol,
            "name": str(meta.get("shortName") or symbol),
            "currency": str(meta.get("currency") or "USD"),
            "price": round(price, 2),
            "change": round(change, 2),
            "change_percent": round((change / previous * 100) if previous else 0.0, 2),
            "spark": [round(float(c), 2) for c in closes[-30:]],
        }
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise FeedError(f"'{symbol}' uchun javob tushunarsiz") from exc

    _cache.put(key, value)
    return {**value, "age_s": 0}


async def fetch_quotes(symbols: list[str]) -> list[dict[str, Any]]:
    """Bir nechta aksiya — parallel.

    Bittasi yiqilsa qolganlari qaytaveradi: bitta noto'g'ri belgi
    butun kartani o'chirib qo'ymasligi kerak.
    """
    results = await asyncio.gather(*(fetch_quote(s) for s in symbols), return_exceptions=True)
    out = [r for r in results if not isinstance(r, BaseException)]
    if not out:
        raise FeedError("Birorta aksiya olinmadi")
    return out


# ── Yangiliklar (RSS, kalitsiz) ───────────────────────────────────

NEWS_TTL_S: Final = 900.0


async def fetch_news(feed_url: str, *, limit: int = 8) -> list[dict[str, str]]:
    """RSS sarlavhalari."""
    key = f"news:{feed_url}:{limit}"
    cached = _cache.get(key, NEWS_TTL_S)
    if cached is not None:
        value, _age = cached
        return list(value)

    response = await _get(feed_url)
    try:
        # `defusedxml` — oddiy `xml.etree` EMAS. RSS tashqi manbadan
        # keladi va standart parser "billion laughs" turidagi hujumga
        # ochiq: bir necha kilobaytlik fayl xotirani to'ldirib
        # serverni yiqitadi. Manba URL sozlamada — ya'ni o'zgarishi
        # mumkin, demak ishonchli deb hisoblab bo'lmaydi.
        root = ElementTree.fromstring(response.text)
    except Exception as exc:
        raise FeedError("RSS o'qib bo'lmadi") from exc

    items: list[dict[str, str]] = []
    # `.//item` — RSS 2.0. Atom (`entry`) ATAYIN qo'llanmaydi: ega
    # bergan manbalar RSS, va ikkala formatni yarim-yarim qo'llash
    # jimgina bo'sh ro'yxatga olib kelardi.
    for item in root.findall(".//item")[:limit]:
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        items.append(
            {
                "title": title,
                "link": (item.findtext("link") or "").strip(),
                "published": (item.findtext("pubDate") or "").strip(),
            }
        )

    if not items:
        raise FeedError("RSS'da yangilik topilmadi")

    _cache.put(key, items)
    return items


# ── Sport (TheSportsDB, ochiq sinov kaliti) ───────────────────────

SPORTS_TTL_S: Final = 600.0
SPORTSDB_KEY: Final = "3"
"""TheSportsDB ochiq sinov kaliti — ro'yxatdan o'tish talab qilmaydi."""


async def fetch_sports(league_id: str) -> list[dict[str, str]]:
    """Ligadagi oxirgi natijalar."""
    key = f"sports:{league_id}"
    cached = _cache.get(key, SPORTS_TTL_S)
    if cached is not None:
        value, _age = cached
        return list(value)

    response = await _get(
        f"https://www.thesportsdb.com/api/v1/json/{SPORTSDB_KEY}/eventspastleague.php",
        params={"id": league_id},
    )
    try:
        events = response.json().get("events") or []
    except ValueError as exc:
        raise FeedError("Sport javobi tushunarsiz") from exc

    out: list[dict[str, str]] = []
    for event in events[:6]:
        home, away = event.get("strHomeTeam"), event.get("strAwayTeam")
        if not home or not away:
            continue
        out.append(
            {
                "home": str(home),
                "away": str(away),
                # Hisob `None` bo'lishi mumkin (o'yin bekor qilingan) —
                # bunda "—" ko'rsatiladi, 0:0 EMAS. 0:0 haqiqiy natija.
                "home_score": str(event.get("intHomeScore") or "—"),
                "away_score": str(event.get("intAwayScore") or "—"),
                "date": str(event.get("dateEvent") or ""),
                "league": str(event.get("strLeague") or ""),
            }
        )

    if not out:
        raise FeedError("Natija topilmadi")

    _cache.put(key, out)
    return out


# ── Valyuta kursi (CBU — O'zbekiston Markaziy banki) ──────────────

RATES_TTL_S: Final = 3600.0


async def fetch_rates(codes: list[str]) -> list[dict[str, Any]]:
    """So'm kursi — Markaziy bankning rasmiy ma'lumoti.

    NEGA QO'SHILDI. Mockupda yo'q edi, lekin ega O'zbekistonda biznes
    yuritadi va USD/EUR kursi unga aksiya narxidan ko'ra ko'proq
    kerak. Manba rasmiy va kalitsiz.
    """
    key = f"rates:{','.join(sorted(codes))}"
    cached = _cache.get(key, RATES_TTL_S)
    if cached is not None:
        value, _age = cached
        return list(value)

    response = await _get("https://cbu.uz/uz/arkhiv-kursov-valyut/json/")
    try:
        rows = response.json()
    except ValueError as exc:
        raise FeedError("Kurs javobi tushunarsiz") from exc

    wanted = {c.strip().upper() for c in codes}
    out = [
        {
            "code": str(r["Ccy"]),
            "name": str(r.get("CcyNm_UZ") or r["Ccy"]),
            "rate": float(r["Rate"]),
            "diff": float(r.get("Diff") or 0.0),
            "date": str(r.get("Date") or ""),
        }
        for r in rows
        if isinstance(r, dict) and str(r.get("Ccy", "")).upper() in wanted
    ]
    if not out:
        raise FeedError("Kurs topilmadi")

    _cache.put(key, out)
    return out


__all__ = [
    "NEWS_TTL_S",
    "STOCKS_TTL_S",
    "WEATHER_TTL_S",
    "FeedError",
    "TTLCache",
    "clear_cache",
    "fetch_news",
    "fetch_quote",
    "fetch_quotes",
    "fetch_rates",
    "fetch_sports",
    "fetch_weather",
]
