"""Kanal moderatsiyasi testlari — sof funksiyalar (Z51, #44).

`classify()` I/O qilmaydi — deterministik, shuning uchun testlar
Bot API bilan aloqasiz, faqat kirish/chiqishni tekshiradi.
"""

from __future__ import annotations

from zet.telegram.moderation import classify


def _message(*, text: str = "", from_id: int = 1, is_bot: bool = False, username: str = "") -> dict:
    return {
        "message_id": 42,
        "text": text,
        "from": {"id": from_id, "is_bot": is_bot, "username": username},
    }


class TestOtherBotMessages:
    def test_message_from_other_bot_is_deleted(self) -> None:
        message = _message(text="salom", is_bot=True, username="spam_bot")

        verdict = classify(message)

        assert verdict.should_delete is True
        assert "spam_bot" in verdict.reason

    def test_own_bot_message_is_not_deleted(self) -> None:
        message = _message(text="salom", from_id=999, is_bot=True)

        verdict = classify(message, own_bot_ids=frozenset({999}))

        assert verdict.should_delete is False

    def test_human_message_is_not_deleted_just_for_being_a_message(self) -> None:
        message = _message(text="Mahsulot bormi?", is_bot=False)

        verdict = classify(message)

        assert verdict.should_delete is False


class TestSpamPattern:
    def test_link_alone_is_not_enough(self) -> None:
        """Faqat havola — mijoz ham havola yuborishi mumkin (masalan manzil)."""
        message = _message(text="Mana manzilim: https://maps.example.com/x")

        verdict = classify(message)

        assert verdict.should_delete is False

    def test_keyword_alone_is_not_enough(self) -> None:
        """Faqat kalit so'z — kontekstsiz o'chirish xato bo'lardi."""
        message = _message(text="crypto haqida savolim bor edi")

        verdict = classify(message)

        assert verdict.should_delete is False

    def test_link_and_keyword_together_is_spam(self) -> None:
        message = _message(text="Bepul pul ishlang! https://scam.example.com/join crypto airdrop")

        verdict = classify(message)

        assert verdict.should_delete is True
        assert "spam naqshi" in verdict.reason

    def test_empty_text_is_not_deleted(self) -> None:
        message = _message(text="")

        verdict = classify(message)

        assert verdict.should_delete is False


class TestMissingFields:
    def test_message_without_from_does_not_crash(self) -> None:
        verdict = classify({"message_id": 1, "text": "salom"})

        assert verdict.should_delete is False

    def test_caption_is_checked_like_text(self) -> None:
        message = {
            "message_id": 1,
            "caption": "Investitsiya kiriting https://scam.example.com airdrop",
            "from": {"id": 1, "is_bot": False},
        }

        verdict = classify(message)

        assert verdict.should_delete is True
