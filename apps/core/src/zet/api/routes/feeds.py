"""Jonli manba endpoint'lari — NEXUS kartalari uchun (Z50).

    GET /api/v1/feeds            — hammasi bitta so'rovda
    GET /api/v1/feeds/weather    — ob-havo
    GET /api/v1/feeds/stocks     — aksiyalar
    GET /api/v1/feeds/news       — yangiliklar
    GET /api/v1/feeds/sports     — sport natijalari
    GET /api/v1/feeds/rates      — valyuta kursi

NEGA BITTA UMUMIY ENDPOINT HAM BOR.

NEXUS ekranida o'nta karta bir vaqtda ko'rinadi. Har biri alohida
so'rov qilsa, brauzer beshta parallel ulanish ochadi va sahifa
ochilishi sekinlashadi. `GET /feeds` hammasini SERVERDA parallel
yig'adi (`asyncio.gather`) va bitta javobda qaytaradi.

ENG MUHIM QARQOR — QISMAN MUVAFFAQIYAT.

Beshta manbadan bittasi yiqilsa, qolgan to'rttasi baribir qaytadi.
Javobda har bir manba uchun `ok` bayrog'i bor: interfeys ishlagan
kartani ko'rsatadi, yiqilganini esa "manba javob bermadi" holatida
chizadi.

Muqobil yo'l — butun so'rovni 502 qilish — yomonroq bo'lardi: bitta
RSS sayt o'chgani uchun ob-havo ham, birja ham yo'qolardi.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from zet.api.deps import get_config
from zet.config import Settings
from zet.feeds import (
    FeedError,
    fetch_news,
    fetch_quotes,
    fetch_rates,
    fetch_sports,
    fetch_weather,
)

router = APIRouter(prefix="/feeds", tags=["feeds"])


class FeedBlock(BaseModel):
    """Bitta manba natijasi — muvaffaqiyat ham, xato ham shu shaklda.

    `ok=False` bo'lganda `data` BO'SH qoladi va `error` to'ladi.
    Soxta qiymat hech qachon qaytmaydi."""

    ok: bool
    source: str
    """Ma'lumot qayerdan keldi — ega manbani ko'rib tursin."""

    data: Any = None
    error: str | None = None


class FeedsResponse(BaseModel):
    weather: FeedBlock
    stocks: FeedBlock
    news: FeedBlock
    sports: FeedBlock
    rates: FeedBlock


def _symbols(settings: Settings) -> list[str]:
    return [s.strip() for s in settings.feed_stock_symbols.split(",") if s.strip()]


def _codes(settings: Settings) -> list[str]:
    return [c.strip() for c in settings.feed_currency_codes.split(",") if c.strip()]


async def _block(source: str, coro: Any) -> FeedBlock:
    """Koroutinni bajarib, natijani yoki XATONI bloklab qaytaradi.

    `FeedError`dan tashqari istisnolar ham ushlanadi: tashqi manba
    kutilmagan shaklda javob berishi mumkin va bu butun `/feeds`
    so'rovini yiqitmasligi kerak."""
    try:
        return FeedBlock(ok=True, source=source, data=await coro)
    except FeedError as exc:
        return FeedBlock(ok=False, source=source, error=str(exc))
    except Exception as exc:
        return FeedBlock(ok=False, source=source, error=f"Kutilmagan xato: {type(exc).__name__}")


@router.get("", response_model=FeedsResponse)
async def all_feeds(settings: Settings = Depends(get_config)) -> FeedsResponse:
    """Barcha jonli manbalar — parallel, qisman muvaffaqiyat bilan."""
    weather, stocks, news, sports, rates = await asyncio.gather(
        _block(
            "Open-Meteo",
            fetch_weather(
                latitude=settings.feed_latitude,
                longitude=settings.feed_longitude,
                timezone=settings.timezone,
            ),
        ),
        _block("Yahoo Finance", fetch_quotes(_symbols(settings))),
        _block("RSS", fetch_news(settings.feed_news_url)),
        _block("TheSportsDB", fetch_sports(settings.feed_sports_league_id)),
        _block("Markaziy bank", fetch_rates(_codes(settings))),
    )
    return FeedsResponse(weather=weather, stocks=stocks, news=news, sports=sports, rates=rates)


@router.get("/weather", response_model=FeedBlock)
async def weather(settings: Settings = Depends(get_config)) -> FeedBlock:
    """Hozirgi ob-havo (Open-Meteo, kalitsiz)."""
    return await _block(
        "Open-Meteo",
        fetch_weather(
            latitude=settings.feed_latitude,
            longitude=settings.feed_longitude,
            timezone=settings.timezone,
        ),
    )


@router.get("/stocks", response_model=FeedBlock)
async def stocks(
    symbols: str = Query(default="", max_length=120),
    settings: Settings = Depends(get_config),
) -> FeedBlock:
    """Aksiya narxlari (Yahoo Finance, kalitsiz)."""
    wanted = [s.strip() for s in symbols.split(",") if s.strip()] or _symbols(settings)
    return await _block("Yahoo Finance", fetch_quotes(wanted))


@router.get("/news", response_model=FeedBlock)
async def news(
    limit: int = Query(default=8, ge=1, le=30),
    settings: Settings = Depends(get_config),
) -> FeedBlock:
    """Yangilik sarlavhalari (RSS, kalitsiz)."""
    return await _block("RSS", fetch_news(settings.feed_news_url, limit=limit))


@router.get("/sports", response_model=FeedBlock)
async def sports(settings: Settings = Depends(get_config)) -> FeedBlock:
    """Oxirgi sport natijalari (TheSportsDB)."""
    return await _block("TheSportsDB", fetch_sports(settings.feed_sports_league_id))


@router.get("/rates", response_model=FeedBlock)
async def rates(settings: Settings = Depends(get_config)) -> FeedBlock:
    """Valyuta kursi (O'zbekiston Markaziy banki)."""
    return await _block("Markaziy bank", fetch_rates(_codes(settings)))


class MusicResponse(BaseModel):
    """MUSIC kartasi — hozircha ulanmagan.

    Mockupdagi karta Spotify/Apple Music kabi SHAXSIY akkauntga
    tayanadi va u OAuth talab qiladi. Kalitsiz haqiqiy manba yo'q,
    o'ylab topilgan to'lqin chizig'i esa aynan ega rad etgan narsa.
    Shuning uchun karta ochiq "ulanmagan" holatda turadi."""

    configured: bool = False
    detail: str = Field(
        default=(
            "Musiqa uchun shaxsiy akkaunt (Spotify) OAuth orqali ulanishi kerak — "
            "kalitsiz haqiqiy manba yo'q."
        )
    )


@router.get("/music", response_model=MusicResponse)
async def music() -> MusicResponse:
    """Musiqa holati — halol 'ulanmagan' javobi."""
    return MusicResponse()


@router.get("/{unknown}", include_in_schema=False)
async def unknown_feed(unknown: str) -> None:
    """Noma'lum manba — 404.

    Aniq xabar bo'lmasa, noto'g'ri yozilgan manba nomi jimgina bo'sh
    javob berib, interfeys "ma'lumot yo'q" deb ko'rsatardi."""
    raise HTTPException(status_code=404, detail=f"'{unknown}' manbasi yo'q")
