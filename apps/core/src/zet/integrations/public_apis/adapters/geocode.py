"""`location.geocode` / `location.reverse_geocode` — Open-Meteo Geocoding
va BigDataCloud reverse-geocode-client (ikkalasi ham HAQIQIY, keyless,
HTTPS — bu sessiyada jonli tekshirilgan, `docs/audits/
PUBLIC_APIS_INTEGRATION_AUDIT.md` §6ga qarang).

NEGA Open-Meteo: `zet/feeds/providers.py::fetch_weather()` ALLAQACHON
shu provayderdan foydalanadi (`weather.now`) — bu YANGI, tekshirilmagan
vendor emas, mavjud ishonch munosabatining kengaytmasi.

O'QISH-FAQAT: joylashuv izlash hech narsani o'zgartirmaydi — natija
UNTRUSTED (A-05), chunki tashqi manbadan keladi.
"""

from __future__ import annotations

from typing import Any

import httpx

from zet.integrations.public_apis.adapters.base import PublicAPIAdapter

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_REVERSE_GEOCODE_URL = "https://api.bigdatacloud.net/data/reverse-geocode-client"


class GeocodeForwardTool(PublicAPIAdapter):
    """Joy nomidan koordinata topadi (Open-Meteo Geocoding API)."""

    @property
    def name(self) -> str:
        return "location.geocode"

    @property
    def provider_name(self) -> str:
        return "open-meteo-geocoding"

    @property
    def description(self) -> str:
        return (
            "O'QISH: Joy nomidan (shahar/qishloq) kenglik/uzunlik koordinatasi "
            "va davlat/vaqt mintaqasi ma'lumotini topadi (masalan 'Toshkent' → "
            "41.26, 69.21). Manzil/koordinatani JOY NOMIGA aylantirish uchun "
            "EMAS — buning uchun location.reverse_geocode."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                    "description": "Joy nomi (shahar, qishloq, mintaqa)",
                },
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "description": "Nechta nomzod qaytarilsin (default 3)",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    async def _call_provider(self, params: dict[str, Any]) -> dict[str, Any]:
        query = str(params["query"]).strip()
        count = int(params.get("count") or 3)
        response = await self._get_client().get(
            _GEOCODE_URL, params={"name": query, "count": count, "format": "json"}
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        # Bo'lim 11: HTTP 200 lekin natija bo'sh — bu SUCCESS, "topilmadi"
        # degani, YOLG'ON emas. `results` kaliti UMUMAN bo'lmasligi mumkin
        # (natija yo'q bo'lganda) — `.get(..., [])` majburiy, `["results"]`
        # bo'lsa hech topilmagan so'rovda `KeyError` bilan yiqilardi.
        results = data.get("results") or []
        return {
            "query": query,
            "total_found": len(results),
            "results": [
                {
                    "name": r.get("name"),
                    "country": r.get("country"),
                    "admin1": r.get("admin1"),
                    "latitude": r.get("latitude"),
                    "longitude": r.get("longitude"),
                    "population": r.get("population"),
                    "timezone": r.get("timezone"),
                }
                for r in results
            ],
            "source": "open-meteo-geocoding",
        }


class GeocodeReverseTool(PublicAPIAdapter):
    """Koordinatadan joy nomini topadi (BigDataCloud reverse-geocode-client)."""

    @property
    def name(self) -> str:
        return "location.reverse_geocode"

    @property
    def provider_name(self) -> str:
        return "bigdatacloud-reverse-geocode-client"

    @property
    def description(self) -> str:
        return (
            "O'QISH: Kenglik/uzunlik koordinatasidan JOY NOMINI (shahar, "
            "mamlakat, hudud) topadi — geocode'ning TESKARISI. Joy nomidan "
            "koordinata topish uchun EMAS — buning uchun location.geocode."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "latitude": {"type": "number", "minimum": -90, "maximum": 90},
                "longitude": {"type": "number", "minimum": -180, "maximum": 180},
            },
            "required": ["latitude", "longitude"],
            "additionalProperties": False,
        }

    async def _call_provider(self, params: dict[str, Any]) -> dict[str, Any]:
        latitude = float(params["latitude"])
        longitude = float(params["longitude"])
        response = await self._get_client().get(
            _REVERSE_GEOCODE_URL,
            params={"latitude": latitude, "longitude": longitude, "localityLanguage": "en"},
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return {
            "latitude": latitude,
            "longitude": longitude,
            "city": data.get("city") or data.get("locality"),
            "locality": data.get("locality"),
            "country": data.get("countryName"),
            "country_code": data.get("countryCode"),
            "principal_subdivision": data.get("principalSubdivision"),
            "continent": data.get("continent"),
            "source": "bigdatacloud-reverse-geocode-client",
        }


def build_geocode_client(*, timeout_s: float = 15.0) -> httpx.AsyncClient:
    """Ikkala geocode adapteri uchun bitta ulashilgan HTTP klient
    yaratish yordamchisi — chaqiruvchi (`build_default_registry()`)
    xohlasa alohida-alohida klient o'rniga shu orqali ulashishi mumkin."""
    return httpx.AsyncClient(timeout=timeout_s)


__all__ = ["GeocodeForwardTool", "GeocodeReverseTool", "build_geocode_client"]
