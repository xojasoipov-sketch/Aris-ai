"""`ip.lookup` — IP manzil geolokatsiyasi (ipwho.is, keyless, HTTPS).

TANLOV TARIXI (halol, `docs/audits/PUBLIC_APIS_INTEGRATION_AUDIT.md`
§6): dastlab `ipapi.co` ko'rib chiqilgan edi (public-apis katalogida
`auth: none` deb belgilangan), lekin bu sessiyada JONLI tekshirilganda
umumiy sandbox IP'dan so'rov HTTP 429 (`RateLimited`) qaytardi —
haqiqiy, jonli signal. `ipwho.is` xuddi shu tekshiruvda muvaffaqiyatli
javob berdi va javob tanasida aniq `success: true/false` maydoniga ega
(Bo'lim 11 talabiga tabiiy mos — HTTP 200 statusi yetarli emasligini
o'zi hisobga oladi).
"""

from __future__ import annotations

import ipaddress
from typing import Any

from zet.integrations.public_apis.adapters.base import PublicAPIAdapter
from zet.tools.base import ToolError, ToolValidationError

_IP_LOOKUP_URL_TEMPLATE = "https://ipwho.is/{ip}"


class IpLookupTool(PublicAPIAdapter):
    """IP manzildan geolokatsiya/tarmoq ma'lumoti (ipwho.is)."""

    @property
    def name(self) -> str:
        return "ip.lookup"

    @property
    def provider_name(self) -> str:
        return "ipwho.is"

    @property
    def description(self) -> str:
        return (
            "O'QISH: IP manzildan taxminiy geolokatsiya (shahar, mamlakat, "
            "vaqt mintaqasi) va tarmoq (ISP) ma'lumotini topadi. Aniqlik "
            "shahar darajasida taxminiy — aniq manzil EMAS (IP geolokatsiya "
            "tabiiy cheklovi)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ip": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 45,
                    "description": "IPv4/IPv6 manzil (masalan 8.8.8.8)",
                },
            },
            "required": ["ip"],
            "additionalProperties": False,
        }

    async def _call_provider(self, params: dict[str, Any]) -> dict[str, Any]:
        ip_raw = str(params["ip"]).strip()
        try:
            ipaddress.ip_address(ip_raw)
        except ValueError as exc:
            # Bo'lim 10: noto'g'ri kirish — tarmoqqa CHIQMASDAN oldin
            # aniq validatsiya xatosi (tashqi provayderga behuda so'rov
            # yubormaslik). `ToolValidationError` (oddiy `ToolError` emas)
            # — `failure_classification.py` buni to'g'ridan-to'g'ri
            # `FailureClass.VALIDATION`ga xaritalaydi (Bo'lim 12: mavjud
            # taksonomiyani qayta ishlatish, yangisini qurmaslik).
            msg = f"{self.provider_name}: '{ip_raw}' haqiqiy IP manzil emas"
            raise ToolValidationError(msg) from exc

        response = await self._get_client().get(_IP_LOOKUP_URL_TEMPLATE.format(ip=ip_raw))
        response.raise_for_status()
        data: dict[str, Any] = response.json()

        # Bo'lim 11 — HTTP 200 YETARLI EMAS: javob tanasida o'zining
        # muvaffaqiyat belgisi bor, buni tekshirmasdan "muvaffaqiyat"
        # deb qaytarish yolg'on natija bo'lardi.
        if data.get("success") is False:
            msg = f"{self.provider_name}: {data.get('message', 'nomalum xato')}"
            raise ToolError(msg)

        connection = data.get("connection") or {}
        timezone = data.get("timezone") or {}
        return {
            "ip": data.get("ip", ip_raw),
            "city": data.get("city"),
            "region": data.get("region"),
            "country": data.get("country"),
            "country_code": data.get("country_code"),
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "timezone": timezone.get("id"),
            "isp": connection.get("isp") or connection.get("org"),
            "source": "ipwho.is",
        }


__all__ = ["IpLookupTool"]
