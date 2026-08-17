"""`zet.voice.transliterate.to_cyrillic()` testlari.

MmsTTS (`voice/mms_tts.py`) faqat kirill matnni tushunadi — bu modul
notoʻgʻri ishlasa, ovoz sifati (talaffuz) buziladi. Shuning uchun aniq
soʻz juftliklari bilan qulflanadi (rasman toʻgʻri kirill yozuvi bilan
solishtirib), shunchaki "funksiya ishlaydi" emas.
"""

from __future__ import annotations

import pytest

from zet.voice.transliterate import to_cyrillic


class TestBasicWords:
    """Keng tarqalgan soʻzlar — rasman toʻgʻri kirill ekvivalenti bilan."""

    @pytest.mark.parametrize(
        ("latin", "cyrillic"),
        [
            ("salom", "салом"),
            ("rahmat", "раҳмат"),
            ("kerak", "керак"),
            ("bugun", "бугун"),
            ("necha", "неча"),
            ("uchrashuv", "учрашув"),
            ("reja", "режа"),
            ("chiqish", "чиқиш"),
            ("tashkil", "ташкил"),
            ("sizga", "сизга"),
            ("bormi", "борми"),
            ("jamoat", "жамоат"),
            ("mijoz", "мижоз"),
            ("qanday", "қандай"),
            ("xursand", "хурсанд"),
            ("odam", "одам"),
        ],
    )
    def test_word_pair(self, latin: str, cyrillic: str) -> None:
        assert to_cyrillic(latin) == cyrillic


class TestDigraphs:
    """`sh`/`ch`/`ng`/`yo`/`yu`/`ya`/`ye` — bitta yoki ikkita kirill harfga."""

    @pytest.mark.parametrize(
        ("latin", "cyrillic"),
        [
            ("shahar", "шаҳар"),
            ("kitob", "китоб"),  # digraf yo'q — nazorat
            ("choy", "чой"),
            ("yangi", "янги"),  # ya + ng
            ("dunyo", "дунё"),  # yo
            ("yulduz", "юлдуз"),  # yu
            ("yaxshi", "яхши"),  # ya, keyin sh
            ("yer", "ер"),  # ye so'z boshida -> е (й- YO'Q)
        ],
    )
    def test_digraph(self, latin: str, cyrillic: str) -> None:
        assert to_cyrillic(latin) == cyrillic


class TestApostropheLetters:
    """`o'`/`g'` — ЎО'zbekcha maxsus harflar, turli apostrof belgilari bilan."""

    @pytest.mark.parametrize("apostrophe", ["'", "’", "ʻ", "ʼ", "`"])
    def test_ozbek_all_apostrophe_variants(self, apostrophe: str) -> None:
        """Odamlar "o'zbek"ni turli klaviatura/OS apostrofi bilan yozadi."""
        assert to_cyrillic(f"o{apostrophe}zbek") == "ўзбек"

    def test_goya(self) -> None:
        assert to_cyrillic("g'oya") == "ғоя"

    def test_tutuq_belgisi_not_confused_with_ou_gu(self) -> None:
        """`o'`/`g'`ga KIRMAGAN qoldiq apostrof — tutuq belgisi (Ъ)."""
        assert to_cyrillic("san'at") == "санъат"

    def test_ou_and_tutuq_in_same_word(self) -> None:
        assert to_cyrillic("to'g'ri") == "тўғри"


class TestEDisambiguation:
    """`e` — soʻz boshida "э", aks holda "е"."""

    def test_word_initial_e_is_e_cyrillic_e(self) -> None:
        assert to_cyrillic("ega") == "эга"
        assert to_cyrillic("elektr") == "электр"

    def test_mid_word_e_is_ye_cyrillic(self) -> None:
        assert to_cyrillic("kerak") == "керак"
        assert to_cyrillic("men") == "мен"

    def test_e_after_word_boundary_resets(self) -> None:
        """Har yangi soʻz boshida qoida qaytadan qoʻllanadi."""
        assert to_cyrillic("u ega") == "у эга"


class TestCasePreservation:
    """Katta/kichik harf original bilan mos boʻlishi kerak."""

    def test_capitalized_word(self) -> None:
        assert to_cyrillic("Salom") == "Салом"

    def test_all_caps(self) -> None:
        assert to_cyrillic("SALOM") == "САЛОМ"

    def test_capitalized_digraph(self) -> None:
        assert to_cyrillic("Shahar") == "Шаҳар"

    def test_all_caps_digraph(self) -> None:
        assert to_cyrillic("SHAHAR") == "ШАҲАР"

    def test_sentence_with_punctuation(self) -> None:
        assert to_cyrillic("Salom, dunyo!") == "Салом, дунё!"


class TestNonLatinPassthrough:
    """Raqam/tinish belgisi/allaqachon kirill matn — oʻzgarishsiz qoladi."""

    def test_numbers_untouched(self) -> None:
        assert to_cyrillic("2026-yil") == "2026-йил"

    def test_punctuation_untouched(self) -> None:
        result = to_cyrillic("Salom, qalaysiz? Yaxshi!")
        assert result == "Салом, қалайсиз? Яхши!"

    def test_empty_string(self) -> None:
        assert to_cyrillic("") == ""

    def test_already_cyrillic_passthrough(self) -> None:
        """Kirill harflar ASCII lotin emas — qayta ishlanmaydi (oʻzgarmaydi)."""
        assert to_cyrillic("салом") == "салом"


class TestSpecialCases:
    def test_q_and_k_distinct(self) -> None:
        """`q` -> қ, `k` -> к — ikkalasi HAM alohida (o'zbekchada ikki xil tovush)."""
        assert to_cyrillic("qaror") == "қарор"
        assert to_cyrillic("kitob") == "китоб"

    def test_x_and_h_distinct(self) -> None:
        """`x` -> х, `h` -> ҳ — ikkalasi HAM alohida."""
        assert to_cyrillic("xat") == "хат"
        assert to_cyrillic("hayot") == "ҳаёт"

    def test_j_is_zhe(self) -> None:
        assert to_cyrillic("jamol") == "жамол"
