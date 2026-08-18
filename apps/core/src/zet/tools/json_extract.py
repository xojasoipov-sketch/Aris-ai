"""LLM javobidan JSON obyekt ajratib olish — YAGONA vakolatli manba (JB-16).

NEGA. Turli tool/modul LLM'dan "faqat JSON qaytar" deb so'raydi, lekin
LLM ba'zan ```json ... ``` bilan o'raydi, oldiga/orqasiga izoh qo'shadi,
yoki hatto JSON qoidabuzarligi qilmasdan ham TOP-DARAJADA dict EMAS
qiymat qaytaradi (masalan bitta satr, ro'yxat, son) — bularning
barchasi sintaktik jihatdan TO'G'RI JSON, lekin chaqiruvchi kod har
doim `dict` kutadi va uni to'g'ridan-to'g'ri `.get(...)` bilan o'qiydi.

ILGARI bu naqsh paket ichida 3 marta MUSTAQIL nusxalangan edi
(`core/recovery.py`, `tools/builtin/vision_ocr.py`,
`tools/builtin/video_learn.py`) — faqat `recovery.py`dagi nusxada
natijaning `dict` ekanligi tekshirilardi. Qolgan ikkitasida bu
tekshiruv YO'Q edi: LLM top-darajada dict-bo'lmagan JSON qaytarganda
(masalan Gemini vision bitta satr — `"rasmda matn topilmadi"` — bilan
javob bersa), `json.loads()` xatosiz `str` qaytaradi, keyingi qatorda
`parsed.get("text")` ishlab chiqarishda `AttributeError: 'str' object
has no attribute 'get'` bilan yiqilardi (JB-16 audit — CASE A).

Bu — `ToolResult.output: Any`dan boshlab hech qayerda "tool/LLM'dan
kelgan xom JSON HAQIQATAN dict-mi" degan savolga YAGONA javob
bo'lmagani uchun yuzaga kelgan tur-shartnoma nomuvofiqligi. Tuzatish
— crash joyida `isinstance()` bilan mudofaa QILISH emas (bu naqsh
qayta-qayta nusxalanishda davom etadi), balki BUTUN paket uchun BITTA
funksiyani majburiy qilish: har bir "LLM matnidan JSON dict ol" joyi
shu yerdan import qiladi, boshqa joyda qayta yozilmaydi.
"""

from __future__ import annotations

import json
from typing import Any


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Matn ichidan birinchi JSON OBYEKTNI (dict) ajratib oladi.

    LLM ba'zan ```json ... ``` fensiga o'raydi yoki oldi/orqasiga
    prose qo'shadi — sof `{...}` blokini tortib olamiz. Natija dict
    BO'LMASA (masalan LLM bitta satr, ro'yxat yoki son qaytarsa) —
    `None` qaytaradi; chaqiruvchi kod xato/fallback qarorini o'zi
    qabul qiladi (bu funksiya hech qachon "dict emas"ni yashirmaydi
    yoki uni majburan dict'ga aylantirmaydi).
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        # ``` yoki ```json bilan boshlanadi
        first_nl = stripped.find("\n")
        if first_nl != -1:
            stripped = stripped[first_nl + 1 :]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()
    # Birinchi '{' dan oxirgi '}' gacha
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    blob = stripped[start : end + 1]
    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


__all__ = ["extract_json_object"]
