"""`zet.voice.text_normalize` testlari — raqam/sana/vaqt/skript normalizatsiyasi.

TTS'ga uzatiladigan matn shu yerda tozalanadi (`navoiy_tts.py`ning
yagona chaqiruvchisi) — noto'g'ri natija noto'g'ri talaffuzga olib
keladi, shuning uchun aniq kutilgan qiymatlar bilan qulflangan.
"""

from __future__ import annotations

import pytest

from zet.voice.text_normalize import (
    cyrillic_to_latin,
    expand_dates,
    expand_numbers,
    expand_times,
    normalize_apostrophes,
    normalize_for_tts,
    number_to_words,
)


class TestNumberToWords:
    @pytest.mark.parametrize(
        ("n", "expected"),
        [
            (0, "nol"),
            (1, "bir"),
            (9, "to'qqiz"),
            (10, "o'n"),
            (11, "o'n bir"),
            (19, "o'n to'qqiz"),
            (20, "yigirma"),
            (21, "yigirma bir"),
            (99, "to'qson to'qqiz"),
            (100, "yuz"),
            (101, "yuz bir"),
            (200, "ikki yuz"),
            (345, "uch yuz qirq besh"),
            (999, "to'qqiz yuz to'qson to'qqiz"),
            (1000, "ming"),
            (1001, "ming bir"),
            (2000, "ikki ming"),
            (2026, "ikki ming yigirma olti"),
            (100000, "yuz ming"),
            (1000000, "million"),
            (2500000, "ikki million besh yuz ming"),
            (1000000000, "milliard"),
        ],
    )
    def test_cardinal(self, n: int, expected: str) -> None:
        assert number_to_words(n) == expected

    def test_negative(self) -> None:
        assert number_to_words(-5) == "minus besh"


class TestExpandNumbers:
    def test_single_number_in_sentence(self) -> None:
        assert expand_numbers("Sizda 3 ta yangi xabar bor") == "Sizda uch ta yangi xabar bor"

    def test_multiple_numbers(self) -> None:
        assert expand_numbers("2 va 5 ta") == "ikki va besh ta"

    def test_no_numbers_untouched(self) -> None:
        assert expand_numbers("Hech qanday raqam yo'q") == "Hech qanday raqam yo'q"


class TestExpandDates:
    def test_full_date(self) -> None:
        assert (
            expand_dates("Bugun 16.07.2026 kuni")
            == "Bugun o'n olti iyul ikki ming yigirma olti yil kuni"
        )

    def test_slash_separator(self) -> None:
        assert "iyul" in expand_dates("16/07/2026")

    def test_invalid_date_untouched(self) -> None:
        """Kun/oy oralig'idan tashqari (masalan 32-kun) — sana emas, o'zgarishsiz."""
        assert expand_dates("32.13.2026") == "32.13.2026"

    def test_no_date_untouched(self) -> None:
        assert expand_dates("Oddiy matn") == "Oddiy matn"


class TestExpandTimes:
    def test_time_with_minutes(self) -> None:
        assert expand_times("soat 14:30 da") == "soat o'n to'rt o'ttiz da"

    def test_time_on_the_hour_no_ortiqcha_soz(self) -> None:
        """Daqiqa 0 bo'lsa — faqat soat aytiladi, "nol" qo'shilmaydi."""
        assert expand_times("soat 9:00 da") == "soat to'qqiz da"

    def test_no_double_soat(self) -> None:
        """REGRESSIYA QOROVULI: "soat" so'zi ikki marta chiqmasin."""
        result = expand_times("soat 14:30 da")
        assert result.count("soat") == 1

    def test_invalid_time_untouched(self) -> None:
        assert expand_times("25:99") == "25:99"


class TestNormalizeApostrophes:
    @pytest.mark.parametrize("apostrophe", ["'", "’", "ʻ", "ʼ", "`"])
    def test_all_variants_to_canonical(self, apostrophe: str) -> None:
        assert normalize_apostrophes(f"o{apostrophe}zbek") == "o'zbek"


class TestCyrillicToLatin:
    @pytest.mark.parametrize(
        ("cyrillic", "latin"),
        [
            ("салом", "salom"),
            ("керак", "kerak"),
            ("ўзбек", "o'zbek"),
            ("ғоя", "g'oya"),
            ("яхши", "yaxshi"),
            ("бугун", "bugun"),
            ("режа", "reja"),
            ("санъат", "san'at"),
        ],
    )
    def test_word_pair(self, cyrillic: str, latin: str) -> None:
        assert cyrillic_to_latin(cyrillic) == latin

    def test_capitalized_digraph_letter(self) -> None:
        """REGRESSIYA QOROVULI: "Я" kabi yakka-katta-harf digraf noto'g'ri
        "YA" (butun katta) emas, "Ya" (bosh harf) bo'lib chiqishi kerak."""
        assert cyrillic_to_latin("Яхши, режа тайёр") == "Yaxshi, reja tayyor"

    def test_all_caps_word(self) -> None:
        assert cyrillic_to_latin("ЯХШИ РЕЖА") == "YAXSHI REJA"

    def test_mixed_script_passthrough(self) -> None:
        assert cyrillic_to_latin("Mixed lotin ва салом matn") == "Mixed lotin va salom matn"

    def test_already_latin_untouched(self) -> None:
        assert cyrillic_to_latin("Salom, dunyo!") == "Salom, dunyo!"

    def test_empty_string(self) -> None:
        assert cyrillic_to_latin("") == ""


class TestNormalizeForTts:
    def test_full_pipeline(self) -> None:
        result = normalize_for_tts("Bugun 16.07.2026, soat 14:30 da uchrashamiz")
        assert (
            result
            == "Bugun o'n olti iyul ikki ming yigirma olti yil, soat o'n to'rt o'ttiz da uchrashamiz"
        )

    def test_cyrillic_input_fully_normalized(self) -> None:
        result = normalize_for_tts("Салом, бугун режа тайёр")
        assert result == "Salom, bugun reja tayyor"

    def test_order_matters_date_before_bare_numbers(self) -> None:
        """Sana avval qayta ishlanishi SHART — aks holda "16"/"07"/"2026"
        alohida-alohida sonlarga bo'linib ketardi."""
        result = normalize_for_tts("16.07.2026")
        assert "o'n olti iyul" in result
        assert "nol yetti" not in result  # "07" alohida son sifatida qolib ketmagan
