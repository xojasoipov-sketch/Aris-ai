"""Katalog kategoriyasi → ZET capability tegi (DETERMINISTIK, LLM YO'Q).

NEGA LLM emas: vazifa tavsifi ochiq taqiqlaydi — "Do not create
unnecessary LLM calls" (tool enumeration/klassifikatsiya uchun ham).
public-apis'ning O'ZI 50 ta kategoriyaga ajratib bergan — bu allaqachon
inson qo'ygan signal, uni qayta LLM bilan "tushunish" ortiqcha xarajat.

Bu xarita TO'LIQ EMAS (50 kategoriyaning barchasi emas) — ATAYLAB:
ZET uchun HOZIRCHA daxldor capability'lar (Bo'lim 21 ustuvorligi +
kengroq foydali guruhlar) xaritalangan. Kategoriyasi xaritada
bo'lmagan yozuv `capabilities=()` bilan qoladi — bu XATO emas, "hali
ZET capability tiliga tarjima qilinmagan" degani; baribir xom
so'z-qidiruv (`search.py`) orqali topiladi.
"""

from __future__ import annotations

# Kategoriya nomi (public-apis'dagi ANIQ matn, pastki registrga
# keltirilgan) → ZET capability teglari.
_CATEGORY_TO_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "geocoding": ("geocoding", "location"),
    "weather": ("weather",),
    "currency exchange": ("currency",),
    "cryptocurrency": ("currency", "finance"),
    "finance": ("finance",),
    "data validation": ("validation", "email_validation", "phone_validation"),
    "email": ("email",),
    "news": ("news",),
    "phone": ("phone_validation",),
    "transportation": ("flight", "transit"),
    "vehicle": ("vehicle",),
    "government": ("government_data",),
    "open data": ("open_data",),
    "science & math": ("science",),
    "sports & fitness": ("sports",),
    "text analysis": ("text_analysis",),
    "translation": ("translation",),
    "url shorteners": ("url_shortening",),
    "screenshot & website analysis": ("screenshot",),
}


def capabilities_for_category(category: str) -> tuple[str, ...]:
    """Kategoriya nomidan ZET capability teglarini qaytaradi.

    Xaritada yo'q kategoriya — bo'sh tuple (xato emas, §modul docstring).
    """
    return _CATEGORY_TO_CAPABILITIES.get(category.strip().lower(), ())


__all__ = ["capabilities_for_category"]
