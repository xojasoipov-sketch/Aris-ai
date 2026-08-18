"""`extract_json_object()` testlari — YAGONA JSON-ajratish manbai (JB-16).

Bu modul `core/recovery.py`, `tools/builtin/vision_ocr.py` va
`tools/builtin/video_learn.py`dagi 3 ta mustaqil nusxalangan
`_extract_json()` funksiyalarini almashtiradi. Eng muhim tekshiruv —
top-darajadagi JSON qiymat `dict` BO'LMASA (LLM bitta satr, ro'yxat
yoki son qaytarsa) funksiya `None` qaytarishi kerak, `AttributeError`
bilan yiqilmasligi yoki xato natijani jimgina dict sifatida
qaytarmasligi kerak (JB-16 CASE A — production crash root cause).
"""

from __future__ import annotations

from zet.tools.json_extract import extract_json_object


class TestValidObjects:
    def test_plain_object(self) -> None:
        assert extract_json_object('{"a": 1}') == {"a": 1}

    def test_markdown_fenced_object(self) -> None:
        assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}

    def test_fenced_without_json_tag(self) -> None:
        assert extract_json_object('```\n{"a": 1}\n```') == {"a": 1}

    def test_object_with_surrounding_prose(self) -> None:
        text = 'Mana natija:\n{"text": "salom", "language": "uz"}\nTugadi.'
        assert extract_json_object(text) == {"text": "salom", "language": "uz"}

    def test_nested_object(self) -> None:
        assert extract_json_object('{"a": {"b": 2}}') == {"a": {"b": 2}}


class TestNonDictTopLevel:
    """LLM top-darajada dict emas qiymat qaytarganda — `None`, crash emas."""

    def test_bare_string(self) -> None:
        assert extract_json_object('"rasmda matn topilmadi"') is None

    def test_bare_list(self) -> None:
        assert extract_json_object("[1, 2, 3]") is None

    def test_bare_number(self) -> None:
        assert extract_json_object("42") is None

    def test_bare_bool(self) -> None:
        assert extract_json_object("true") is None


class TestInvalidOrMissingJson:
    def test_no_json_at_all(self) -> None:
        assert extract_json_object("just some plain text") is None

    def test_empty_string(self) -> None:
        assert extract_json_object("") is None

    def test_malformed_braces(self) -> None:
        assert extract_json_object("{not: valid, json}") is None

    def test_unbalanced_braces(self) -> None:
        assert extract_json_object('{"a": 1') is None
