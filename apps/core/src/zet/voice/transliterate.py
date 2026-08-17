"""O'zbek lotin → kirill transliteratsiyasi.

NEGA KERAK. `facebook/mms-tts-uzb-script_cyrillic` (Meta MMS-TTS, bo'lim
`mms_tts.py`) FAQAT kirill matnni tushunadi — modelning o'zi lotin
skriptida o'qitilmagan. ZET esa (agent javoblari, foydalanuvchi xabarlari)
lotin yozuvida ishlaydi. Shuning uchun TTS'ga uzatishdan oldin matn
kirillga o'giriladi — bu ovoz sifatiga bevosita ta'sir qiladi: noto'g'ri
transliteratsiya noto'g'ri talaffuzga olib keladi.

QOIDALAR — rasman O'zbekiston Davlat til qo'mitasining lotin↔kirill
muvofiqlik jadvaliga asoslangan (eng ko'p qo'llaniladigan holatlar):

    Digraflar (2 harf → 1 yoki 2 kirill harf, ENG UZUN MOS KELISHI
    birinchi tekshiriladi — "sh" "s"dan OLDIN):
        sh → ш     ch → ч     ng → нг
        yo → ё     yu → ю     ya → я     ye → е
        o' → ў     g' → ғ     (apostrof: ' ʻ ʼ ' ` — barchasi tan olinadi)

    Yakka harflar:
        a→а b→б d→д e→е(*) f→ф g→г h→ҳ i→и j→ж k→к l→л m→м n→н
        o→о p→п q→қ r→р s→с t→т u→у v→в x→х y→й z→з c→ц(**)

    (*) "e" so'z BOSHIDA → э (masalan "ega"→"эга", "elektr"→"электр"),
        so'z ICHIDA/OXIRIDA → е (masalan "kerak"→"керак", "men"→"мен").
        Bu eng keng tarqalgan holatni to'g'ri qamrab oladi, lekin unli
        harfdan keyingi hiatus holatlari (masalan ba'zi qo'shma so'zlar)
        alohida tekshirilmagan — BILINGAN CHEKLOV.
    (**) "c" o'zbek lotin alifbosida mustaqil harf sifatida deyarli
        ishlatilmaydi (faqat "ch" digrafi ichida) — yakka "c" faqat
        chet so'z/ism uchun zaxira sifatida "ц"ga o'giriladi.

    Qoldiq apostrof (o'/g' digrafiga kirmagan, ya'ni "tutuq belgisi",
    Ъ harfini bildiradi — masalan "san'at" → "санъат") → ъ.

BILINGAN CHEKLOVLAR (yashirilmaydi):
    - э/е farqi faqat so'z boshi/o'rtasi qoidasi bilan taxminiy hal
      qilinadi — ayrim qo'shma so'zlarda xato bo'lishi mumkin.
    - Chet so'zlar/ismlar (ayniqsa rus/ingliz kelib chiqishi) uchun
      to'liq to'g'ri emas — ular kirill originalida alohida yozilishi
      kerak bo'ladi.
    - Raqamlar, tinish belgilari va lotin bo'lmagan belgilar
      o'zgarishsiz qoladi.

Bog'liq: `zet/voice/mms_tts.py` (yagona chaqiruvchi).
"""

from __future__ import annotations

import re

# Apostrofga o'xshash barcha belgilar — odamlar "o'zbek" so'zini turli
# klaviatura/OS'da turlicha apostrof bilan yozadi (to'g'ri ASCII ', smart
# quote ', modifier letter turned comma ʻ, modifier letter apostrophe ʼ).
# Barchasi bitta kanonik ASCII apostrofga normallashtiriladi, shundan
# keyin digraf jadvali faqat bitta variantni bilishi kifoya qiladi.
_APOSTROPHE_CHARS = "'’ʻʼ`"
_APOSTROPHE_RE = re.compile(f"[{_APOSTROPHE_CHARS}]")

# Digraflar — ENG UZUNI birinchi (2 harfli kalitlar), pastda yakka
# harflar bilan birlashtirib bitta lug'atga yig'iladi va kalit uzunligi
# bo'yicha KAMAYISH tartibida tekshiriladi (greedy longest-match).
_DIGRAPHS: dict[str, str] = {
    "sh": "ш",
    "ch": "ч",
    "ng": "нг",
    "yo": "ё",
    "yu": "ю",
    "ya": "я",
    "ye": "е",
    "o'": "ў",
    "g'": "ғ",
}

_SINGLES: dict[str, str] = {
    "a": "а",
    "b": "б",
    "d": "д",
    "e": "е",  # so'z boshida alohida hal qilinadi, pastga qarang
    "f": "ф",
    "g": "г",
    "h": "ҳ",
    "i": "и",
    "j": "ж",
    "k": "к",
    "l": "л",
    "m": "м",
    "n": "н",
    "o": "о",
    "p": "п",
    "q": "қ",
    "r": "р",
    "s": "с",
    "t": "т",
    "u": "у",
    "v": "в",
    "x": "х",
    "y": "й",
    "z": "з",
    "c": "ц",  # faqat chet so'z zaxirasi — modul docstring'iga qarang
}

_WORD_BOUNDARY = re.compile(r"[^a-zA-Z']+")
"""So'z boshini aniqlash uchun — harf/apostrofdan boshqa har qanday belgi
so'z chegarasi hisoblanadi (bo'shliq, tinish belgisi, raqam)."""


def _apply_case(cyrillic: str, latin_chunk: str) -> str:
    """Kirill natijasiga lotin original harflarining katta/kichikligini qo'llaydi.

    Uch holat: BUTUNLAY KATTA ("SH" → "Ш"), Bosh harf ("Sh" → "Ш" — birinchi
    kirill harfi katta, qolgani kichik), yoki kichik ("sh" → "ш").
    """
    if latin_chunk.isupper():
        return cyrillic.upper()
    if latin_chunk[0].isupper():
        return cyrillic[0].upper() + cyrillic[1:]
    return cyrillic


def to_cyrillic(text: str) -> str:
    """O'zbek lotin matnini kirillga o'giradi.

    Lotin bo'lmagan belgilar (raqam, tinish belgisi, bo'shliq, allaqachon
    kirill/boshqa yozuvdagi matn) O'ZGARISHSIZ qoladi — faqat ASCII
    lotin harflari (va ular bilan bog'liq apostroflar) qayta ishlanadi.
    """
    if not text:
        return text

    normalized = _APOSTROPHE_RE.sub("'", text)
    result: list[str] = []
    i = 0
    n = len(normalized)
    at_word_start = True

    while i < n:
        ch = normalized[i]
        if not (ch.isalpha() and ch.isascii()) and ch != "'":
            result.append(ch)
            at_word_start = bool(_WORD_BOUNDARY.fullmatch(ch))
            i += 1
            continue

        # 2 harfli digraf — greedy, "sh"/"ch"/"ng"/"yo"/"yu"/"ya"/"ye"/"o'"/"g'"
        two = normalized[i : i + 2].lower()
        if two in _DIGRAPHS:
            result.append(_apply_case(_DIGRAPHS[two], normalized[i : i + 2]))
            i += 2
            at_word_start = False
            continue

        low = ch.lower()
        if low == "e":
            # so'z boshida "e" → "э" (masalan "ega"→"эга"), aks holda "е"
            cyrillic_e = "э" if at_word_start else "е"
            result.append(cyrillic_e.upper() if ch.isupper() else cyrillic_e)
            i += 1
            at_word_start = False
            continue
        if low in _SINGLES:
            result.append(_apply_case(_SINGLES[low], ch))
            i += 1
            at_word_start = False
            continue
        if ch == "'":
            # o'/g' digrafiga kirmagan qoldiq apostrof — tutuq belgisi (Ъ)
            result.append("ъ")
            i += 1
            at_word_start = False
            continue

        # Yuqoridagi shartlarga tushmagan ASCII harf (nazariy jihatdan
        # bo'lmasligi kerak — alifboning barcha harflari qamrab olingan)
        result.append(ch)
        i += 1
        at_word_start = False

    return "".join(result)


__all__ = ["to_cyrillic"]
