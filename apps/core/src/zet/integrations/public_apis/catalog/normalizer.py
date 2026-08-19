"""`RawEntry` → `PublicAPIEntry` — maydonlarni normallashtirish.

MUHIM QOIDA (vazifa tavsifida ochiq talab qilingan): `pricing_status`
xom parse paytida HECH QACHON "free" deb taxmin qilinmaydi — public-apis
bu ma'lumotni umuman bermaydi. Har doim `UNKNOWN`; faqat qo'lda
tekshirilgan `adapters/`dagi kod o'zi (yozuvni emas, ADAPTER metadata'sini)
"bepul" deb belgilaydi.
"""

from __future__ import annotations

from urllib.parse import urlparse

from zet.integrations.public_apis.catalog.models import (
    APIStatus,
    AuthType,
    PricingStatus,
    PublicAPIEntry,
    entry_id,
)
from zet.integrations.public_apis.catalog.parser import RawEntry

SOURCE_NAME = "public-apis"
SOURCE_REPOSITORY = "public-apis/public-apis"

_AUTH_MAP: dict[str, AuthType] = {
    "no": AuthType.NONE,
    "none": AuthType.NONE,
    "apikey": AuthType.API_KEY,
    "oauth": AuthType.OAUTH,
    "bearer": AuthType.BEARER,
    "basic": AuthType.BASIC,
}


def _normalize_auth(auth_raw: str) -> AuthType:
    cleaned = auth_raw.strip().strip("`").strip().lower()
    if not cleaned:
        return AuthType.UNKNOWN
    mapped = _AUTH_MAP.get(cleaned)
    if mapped is not None:
        return mapped
    # Backtick bilan o'ralgan, lekin ro'yxatda yo'q qiymat (masalan
    # `X-Mashape-Key`, `User-Agent`) — hali ham "kalit/sarlavha talab
    # qiladi" degani, shuning uchun CUSTOM (UNKNOWN emas — biz aslida
    # NIMA talab qilinishini bilamiz, faqat standart toifaga
    # tushmaydi).
    return AuthType.CUSTOM


def _normalize_bool(raw: str) -> bool:
    return raw.strip().lower() == "yes"


def _normalize_optional_bool(raw: str) -> bool | None:
    cleaned = raw.strip().lower()
    if cleaned == "yes":
        return True
    if cleaned == "no":
        return False
    return None  # "Unknown" yoki bo'sh


def _provider_from_url(url: str, *, fallback_name: str) -> str:
    try:
        host = urlparse(url).netloc
    except ValueError:
        host = ""
    host = host.removeprefix("www.")
    return host or fallback_name


def normalize_entry(raw: RawEntry) -> PublicAPIEntry:
    """Bitta xom qatorni to'liq `PublicAPIEntry`ga o'giradi."""
    auth_type = _normalize_auth(raw.auth_raw)
    return PublicAPIEntry(
        id=entry_id(category=raw.category, name=raw.name),
        name=raw.name,
        description=raw.description,
        category=raw.category,
        documentation_url=raw.homepage_url,
        homepage_url=raw.homepage_url,
        auth_type=auth_type,
        https_supported=_normalize_bool(raw.https_raw),
        cors_supported=_normalize_optional_bool(raw.cors_raw),
        source=SOURCE_NAME,
        source_repository=SOURCE_REPOSITORY,
        pricing_status=PricingStatus.UNKNOWN,  # QOIDA: hech qachon taxmin qilinmaydi
        api_key_required=auth_type != AuthType.NONE,
        provider=_provider_from_url(raw.homepage_url, fallback_name=raw.name),
        status=APIStatus.DISCOVERED,
    )


def normalize_entries(raw_entries: list[RawEntry]) -> list[PublicAPIEntry]:
    return [normalize_entry(r) for r in raw_entries]


__all__ = ["normalize_entries", "normalize_entry"]
