"""TTS'dan oldingi matn normalizatsiyasi — raqam/sana/vaqt/skript/apostrof.

NEGA. TTS modeli (`mms_tts.py`, kelajakda `navoiy_tts.py`) matnni HARF
MA'NOSIDA o'qiydi — "16.07.2026" deb yozilgan narsani "bir olti nuqta
nol yetti..." deb talaffuz qilishi mumkin, "o'n olti iyul ikki ming
yigirma olti yil" o'rniga. Bu modul TTS'ga uzatishdan OLDIN matnni
INSON O'QIYDIGAN so'z shakliga o'giradi.

Bosqichlar (tartib MUHIM — har biri keyingisiga tayyorlaydi):
    1. `normalize_apostrophes()` — turli apostrof belgilarini (', ', ʻ,
       ʼ, `) bitta kanonik ASCII apostrofga keltiradi.
    2. `cyrillic_to_latin()` — agar matn (yoki matn bo'lagi) kirill
       yozuvida bo'lsa, lotinga o'giradi — `transliterate.to_cyrillic()`
       ning TESKARI yo'nalishi. Bu bilan keyingi bosqichlar (raqam/sana)
       FAQAT bitta skript (lotin) bilan ishlashi kifoya qiladi.
    3. `expand_dates()` — `DD.MM.YYYY` / `DD/MM/YYYY` → so'z shakli.
    4. `expand_times()` — `HH:MM` → so'z shakli.
    5. `expand_numbers()` — qolgan yakka butun sonlarni so'zga o'giradi.
    6. `normalize_for_tts()` — yuqoridagi hammasini TO'G'RI TARTIBDA
       ishga tushiruvchi yagona kirish nuqtasi.

BILINGAN CHEKLOVLAR (yashirilmaydi):
    - Faqat BUTUN sonlar (0 dan trillionlargacha) qo'llab-quvvatlanadi
      — kasr sonlar ("3.14"), tartib sonlar ("5-", "o'ninchi" formatida
      emas, "5" raqami sifatida o'qiladi) TO'LIQ hal qilinmagan.
    - Sana faqat `DD.MM.YYYY`/`DD/MM/YYYY` formatida tanilanadi — "16-iyul"
      yoki "2026-yil 16-iyul" kabi aralash formatlar QOPLANMAGAN.
    - Vaqt faqat `HH:MM` (24 soatlik) formatida — "14:30:00" (soniya
      bilan) yoki "2 PM" kabi format QOPLANMAGAN.
    - `cyrillic_to_latin()` — `transliterate.to_cyrillic()`ning aniq
      teskarisi emas (ba'zi kirill harflar bir nechta lotin ekvivalentga
      mos kelishi mumkin, masalan е → e/ye kontekstga qarab) — eng keng
      tarqalgan holat qamrab olingan, 100% aniqlik va'da qilinmaydi.
"""

from __future__ import annotations

import re

_APOSTROPHE_CHARS = "'’ʻʼ`"
_APOSTROPHE_RE = re.compile(f"[{_APOSTROPHE_CHARS}]")


def normalize_apostrophes(text: str) -> str:
    """Turli apostrof belgilarini bitta kanonik ASCII apostrofga keltiradi."""
    return _APOSTROPHE_RE.sub("'", text)


# ── Kirill → lotin (cheklangan, eng keng tarqalgan xarita) ────────────

_CYRILLIC_TO_LATIN_DIGRAPHS: dict[str, str] = {
    "ш": "sh",
    "ч": "ch",
    "нг": "ng",
    "ё": "yo",
    "ю": "yu",
    "я": "ya",
    "ў": "o'",
    "ғ": "g'",
    "ъ": "'",
}

_CYRILLIC_TO_LATIN_SINGLES: dict[str, str] = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ж": "j",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "қ": "q",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "x",
    "ҳ": "h",
    "ц": "ts",
    "э": "e",
}

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
"""Harflardan iborat uzluksiz bo'lak — raqam/tinish belgisi/bo'shliq EMAS.

So'z darajasida ishlash SHART: kirill digraflarning aksariyati (я/ё/ю/ш/ч
va h.k.) BITTA kirill harfdan 2 harfli lotin digrafiga o'tadi — bu degani
"Я" kabi YAKKA katta harfdan uni so'z BOSHImi ("Yaxshi") yoki so'z BUTUN
KATTA HARFLI ("YAXSHI") ekanini bilib bo'lmaydi. Butun so'zni ko'rib,
keyin katta/kichik naqshni QAYTA QO'LLASH kerak (harf-ma-harf emas).
"""


def _cyrillic_word_to_latin(word: str) -> str:
    low = word.lower()
    result: list[str] = []
    i = 0
    n = len(low)
    while i < n:
        two = low[i : i + 2]
        if two == "нг":
            result.append("ng")
            i += 2
            continue
        ch = low[i]
        if ch in _CYRILLIC_TO_LATIN_DIGRAPHS:
            result.append(_CYRILLIC_TO_LATIN_DIGRAPHS[ch])
        elif ch in _CYRILLIC_TO_LATIN_SINGLES:
            result.append(_CYRILLIC_TO_LATIN_SINGLES[ch])
        else:
            result.append(ch)  # allaqachon lotin/boshqa belgi — o'zgarishsiz
        i += 1
    converted = "".join(result)

    if word.isupper():
        return converted.upper()
    if word[:1].isupper():
        return converted[:1].upper() + converted[1:]
    return converted


def cyrillic_to_latin(text: str) -> str:
    """Kirill matnni lotinga o'giradi — `transliterate.to_cyrillic()`ning teskarisi.

    Faqat kirill HARFLARGA ta'sir qiladi — lotin, raqam, tinish belgisi
    o'zgarishsiz qoladi (matn allaqachon lotin bo'lsa, bu funksiya
    haqiqatda hech narsa qilmaydi — xavfsiz, cheklovsiz chaqirsa bo'ladi).
    """
    if not text:
        return text
    return _WORD_RE.sub(lambda m: _cyrillic_word_to_latin(m.group()), text)


# ── Sonlarni so'zga o'girish ────────────────────────────────────────

_ONES = ["", "bir", "ikki", "uch", "to'rt", "besh", "olti", "yetti", "sakkiz", "to'qqiz"]
_TENS = ["", "o'n", "yigirma", "o'ttiz", "qirq", "ellik", "oltmish", "yetmish", "sakson", "to'qson"]
_SCALES = [(1_000_000_000, "milliard"), (1_000_000, "million"), (1_000, "ming")]


def _three_digits_to_words(n: int) -> str:
    """0-999 oralig'idagi sonni so'zga o'giradi."""
    if n == 0:
        return ""
    parts: list[str] = []
    hundreds, rem = divmod(n, 100)
    if hundreds:
        parts.append(_ONES[hundreds] if hundreds > 1 else "")
        parts.append("yuz")
    tens, ones = divmod(rem, 10)
    if tens:
        parts.append(_TENS[tens])
    if ones:
        parts.append(_ONES[ones])
    return " ".join(p for p in parts if p)


def number_to_words(n: int) -> str:
    """Butun sonni o'zbekcha so'z shakliga o'giradi (0 dan trillionlargacha).

    Manfiy sonlar uchun "minus" prefiksi qo'shiladi.
    """
    if n < 0:
        return f"minus {number_to_words(-n)}"
    if n == 0:
        return "nol"

    parts: list[str] = []
    remainder = n
    for scale_value, scale_name in _SCALES:
        if remainder >= scale_value:
            count, remainder = divmod(remainder, scale_value)
            count_words = _three_digits_to_words(count)
            # "bir ming" emas, "ming" — o'zbekchada 1000 oddiy "ming"
            # deyiladi (rus/ingliz "one thousand"dan farqli), lekin
            # "ikki ming"/"uch ming" kabi holatlarda son aytiladi.
            if count == 1:
                parts.append(scale_name)
            else:
                parts.append(f"{count_words} {scale_name}")
    if remainder:
        parts.append(_three_digits_to_words(remainder))

    return " ".join(p for p in parts if p)


_NUMBER_RE = re.compile(r"(?<![\d.:/])-?\d+(?![\d.:/])")


def expand_numbers(text: str) -> str:
    """Matndagi yakka butun sonlarni so'zga o'giradi.

    Sana (`DD.MM.YYYY`)/vaqt (`HH:MM`) allaqachon `expand_dates()`/
    `expand_times()` bilan qayta ishlangan bo'lishi kerak — bu funksiya
    ULARDAN KEYIN chaqiriladi (`normalize_for_tts()`dagi tartibga qarang),
    aks holda "16.07.2026" kabi satrlar "16" "07" "2026" alohida-alohida
    sonlarga bo'linib ketardi.
    """
    return _NUMBER_RE.sub(lambda m: number_to_words(int(m.group())), text)


# ── Sana va vaqt ────────────────────────────────────────────────────

_MONTHS = [
    "yanvar",
    "fevral",
    "mart",
    "aprel",
    "may",
    "iyun",
    "iyul",
    "avgust",
    "sentyabr",
    "oktyabr",
    "noyabr",
    "dekabr",
]

_DATE_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")


def expand_dates(text: str) -> str:
    """`DD.MM.YYYY`/`DD/MM/YYYY` → so'z shakli (masalan "16.07.2026" → "o'n olti iyul ikki ming yigirma olti yil")."""

    def _replace(m: re.Match[str]) -> str:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1 <= day <= 31 and 1 <= month <= 12):
            return m.group()  # haqiqiy sana emas — o'zgarishsiz qoldiriladi
        return f"{number_to_words(day)} {_MONTHS[month - 1]} {number_to_words(year)} yil"

    return _DATE_RE.sub(_replace, text)


def expand_times(text: str) -> str:
    """`HH:MM` (24 soatlik) → so'z shakli (masalan "14:30" → "o'n to'rt o'ttiz").

    "soat" SO'ZI QO'SHILMAYDI — asl matnda odatda allaqachon bor
    ("soat 14:30 da" → "soat o'n to'rt o'ttiz da"). Agar bu funksiyaning
    o'zi ham "soat" qo'shsa, natija "soat soat ..." bo'lib qo'shaloq
    chiqadi — bu aynan shu sababdan ATAYLAB qilinmagan.
    """

    def _replace(m: re.Match[str]) -> str:
        hour, minute = int(m.group(1)), int(m.group(2))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return m.group()
        if minute == 0:
            return number_to_words(hour)
        return f"{number_to_words(hour)} {number_to_words(minute)}"

    return _TIME_RE.sub(_replace, text)


def normalize_for_tts(text: str) -> str:
    """To'liq normalizatsiya zanjiri — TTS'ga uzatishdan OLDIN chaqiriladi.

    Tartib MUHIM: apostrof → skript → sana → vaqt → qolgan sonlar.
    Sana/vaqt sonlardan OLDIN qayta ishlanishi shart — aks holda
    "16.07.2026" alohida "16"/"07"/"2026" sonlariga bo'linib ketadi.
    """
    text = normalize_apostrophes(text)
    text = cyrillic_to_latin(text)
    text = expand_dates(text)
    text = expand_times(text)
    return expand_numbers(text)


__all__ = [
    "cyrillic_to_latin",
    "expand_dates",
    "expand_numbers",
    "expand_times",
    "normalize_apostrophes",
    "normalize_for_tts",
    "number_to_words",
]
