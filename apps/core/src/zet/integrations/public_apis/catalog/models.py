"""public-apis katalogi — normallashtirilgan ichki model.

NEGA. `public-apis/public-apis` repozitoriysi — README.md ichida
markdown jadval, hech qanday shartnoma/schema kafolati yo'q. Bu modul
o'sha xom qatorlarni ZET ICHIDA barqaror, tekshiriladigan modelga
o'giradi — DISCOVERY va ADAPTER qatlamlari faqat shu modelga qaraydi,
xom markdown'ga emas.

MUHIM (Bo'lim 22 — "public-apis manba ishonch ildizi emas"): bu
modeldagi HECH BIR qiymat "xavfsiz"/"ishonchli"/"bepul" degani EMAS —
faqat public-apis ONIMA E'LON QILGANI. `status=DISCOVERED` — hali
BAHOLANMAGAN. Faqat ushbu repo ICHIDA yozilgan, ko'rib chiqilgan
adapter orqali `status=ENABLED`ga o'tadi (`adapters/`ga qarang).

`pricing_status` — public-apis'dan HECH QACHON avtomatik "free" deb
xulosa chiqarilmaydi (vazifa tavsifidagi ochiq talab): xom parse
paytida har doim UNKNOWN, faqat qo'lda tekshirilgan adapter o'zi
override qiladi.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class AuthType(StrEnum):
    """public-apis'ning `Auth` ustunidagi qiymatlarga mos keladi."""

    NONE = "none"
    API_KEY = "apiKey"
    OAUTH = "OAuth"
    BEARER = "bearer"
    BASIC = "basic"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


class PricingStatus(StrEnum):
    """Narxlash holati — public-apis buni UMUMAN bermaydi, shuning
    uchun xom parse natijasi doim UNKNOWN."""

    FREE = "free"
    FREEMIUM = "freemium"
    PAID = "paid"
    UNKNOWN = "unknown"


class APIStatus(StrEnum):
    """Katalog yozuvining HAYOT SIKLI holati (Bo'lim 22 — ishonch bosqichlari).

    DISCOVERED — katalogdan o'qildi, hech kim ko'rib chiqmagan.
    EVALUATED — inson/audit ko'rib chiqdi, qaror hali yo'q.
    ENABLED — ushbu repo ichida haqiqiy `Tool` adapter yozilgan va
        `ToolRegistry`ga ro'yxatga olingan — FAQAT shu holat ijro
        etiladigan demak.
    REJECTED — ko'rib chiqildi va ATAYLAB ishlatilmaydi deb qaror
        qilindi (masalan kalit talab qiladi, ishonchsiz, ToS mos emas).
    DISABLED — ilgari ENABLED edi, keyin o'chirilgan (masalan sog'liq
        pasaygani uchun).
    """

    DISCOVERED = "discovered"
    EVALUATED = "evaluated"
    ENABLED = "enabled"
    REJECTED = "rejected"
    DISABLED = "disabled"


def entry_id(*, category: str, name: str) -> str:
    """Barqaror, deterministik ID — kategoriya+nom bo'yicha (JB — katalog
    qayta sync qilinganda BIR XIL yozuv BIR XIL ID olishi shart, aks
    holda har sync "hammasi yangi" deb ko'rsatardi)."""
    raw = f"{category.strip().lower()}::{name.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class PublicAPIEntry:
    """Bitta tashqi API'ning normallashtirilgan ichki tasviri."""

    id: str
    name: str
    description: str
    category: str
    documentation_url: str
    homepage_url: str
    auth_type: AuthType
    https_supported: bool
    cors_supported: bool | None
    """`None` — public-apis "Unknown" deb yozgan yoki ustun bo'sh."""
    source: str
    source_repository: str
    pricing_status: PricingStatus
    api_key_required: bool
    provider: str
    capabilities: tuple[str, ...] = ()
    """Discovery/capability_mapper to'ldiradi — parse vaqtida bo'sh."""
    status: APIStatus = APIStatus.DISCOVERED
    trust_score: float = 0.0
    health_score: float | None = None
    last_checked: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_capabilities(self, capabilities: tuple[str, ...]) -> PublicAPIEntry:
        """Yangi capability ro'yxati bilan nusxa (frozen — mutatsiya emas)."""
        return _replace_frozen(self, capabilities=capabilities)

    def with_status(self, status: APIStatus) -> PublicAPIEntry:
        return _replace_frozen(self, status=status)

    def with_health(self, *, health_score: float, last_checked: datetime) -> PublicAPIEntry:
        return _replace_frozen(self, health_score=health_score, last_checked=last_checked)


def _replace_frozen(entry: PublicAPIEntry, **changes: Any) -> PublicAPIEntry:
    """`dataclasses.replace()` — `frozen=True, slots=True` bilan ham ishlaydi."""
    import dataclasses

    return dataclasses.replace(entry, **changes)


__all__ = [
    "APIStatus",
    "AuthType",
    "PricingStatus",
    "PublicAPIEntry",
    "entry_id",
]
