"""TelegramPoller testlari — Bot API long-polling (V-17, ADR-0007).

respx bilan `httpx` chaqiruvlari mock qilinadi. Loop `run_forever()`
ni to'liq sinash o'rniga, bitta iteratsiya (`_get_updates` +
`_process_update` + `_send_reply`) alohida chaqiriladi — bu tarmoqqa
chiqmasdan xato ehtimolini eng aniq ko'rsatadi.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from zet.telegram.bot import ZetBot
from zet.telegram.handlers import TelegramOutput
from zet.telegram.polling import TelegramPoller

_TOKEN = "test-token"
_BASE = "https://api.telegram.org"
_OWNER_ID = 42


@pytest.fixture
def bot() -> ZetBot:
    """Faqat owner allowlist bilan test ZetBot (polling ishga tushirilmaydi)."""
    return ZetBot(token=_TOKEN, owner_ids={_OWNER_ID})


def _message_update(update_id: int, **message_fields: object) -> dict[str, object]:
    """Bitta getUpdates yozuvi — message wrapper bilan."""
    default_msg: dict[str, object] = {
        "message_id": 1,
        "from": {"id": _OWNER_ID, "is_bot": False},
        "chat": {"id": _OWNER_ID, "type": "private"},
    }
    default_msg.update(message_fields)
    return {"update_id": update_id, "message": default_msg}


class TestGetUpdates:
    @respx.mock
    async def test_advances_offset_after_batch(self, bot: ZetBot) -> None:
        respx.get(f"{_BASE}/bot{_TOKEN}/getUpdates").mock(
            return_value=httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": [
                        _message_update(10, text="a"),
                        _message_update(11, text="b"),
                    ],
                },
            )
        )
        poller = TelegramPoller(token=_TOKEN, bot=bot)
        try:
            updates = await poller._get_updates()
            assert len(updates) == 2
            # offset = max(update_id) + 1
            assert poller._offset == 12
        finally:
            await poller.aclose()

    @respx.mock
    async def test_ok_false_returns_empty(self, bot: ZetBot) -> None:
        respx.get(f"{_BASE}/bot{_TOKEN}/getUpdates").mock(
            return_value=httpx.Response(200, json={"ok": False, "description": "bad"})
        )
        poller = TelegramPoller(token=_TOKEN, bot=bot)
        try:
            assert await poller._get_updates() == []
        finally:
            await poller.aclose()


class TestProcessUpdate:
    @respx.mock
    async def test_text_message_gets_reply(self, bot: ZetBot) -> None:
        send_route = respx.post(f"{_BASE}/bot{_TOKEN}/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        poller = TelegramPoller(token=_TOKEN, bot=bot)
        try:
            await poller._process_update(_message_update(1, text="Salom"))
        finally:
            await poller.aclose()

        assert send_route.called
        body = send_route.calls[0].request.content
        # Echo yo'li: "Qabul qilindi" + asl matn
        assert b"Qabul qilindi" in body
        assert b"Salom" in body

    @respx.mock
    async def test_non_owner_message_ignored(self, bot: ZetBot) -> None:
        stranger = {
            "update_id": 5,
            "message": {
                "message_id": 1,
                "from": {"id": 999, "is_bot": False},
                "chat": {"id": 999, "type": "private"},
                "text": "hi",
            },
        }
        send_route = respx.post(f"{_BASE}/bot{_TOKEN}/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        poller = TelegramPoller(token=_TOKEN, bot=bot)
        try:
            await poller._process_update(stranger)
        finally:
            await poller.aclose()

        assert not send_route.called

    @respx.mock
    async def test_voice_downloads_file_and_transcribes(self, bot: ZetBot) -> None:
        """Voice → getFile → download → STT → Orchestrator (StubSTT default matn)."""
        respx.post(f"{_BASE}/bot{_TOKEN}/getFile").mock(
            return_value=httpx.Response(
                200, json={"ok": True, "result": {"file_path": "voice/x.ogg"}}
            )
        )
        respx.get(f"{_BASE}/file/bot{_TOKEN}/voice/x.ogg").mock(
            return_value=httpx.Response(200, content=b"OGG-BYTES")
        )
        send_route = respx.post(f"{_BASE}/bot{_TOKEN}/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )

        voice_update = _message_update(
            20, voice={"file_id": "AwACAg", "duration": 2, "mime_type": "audio/ogg"}
        )
        poller = TelegramPoller(token=_TOKEN, bot=bot)
        try:
            await poller._process_update(voice_update)
        finally:
            await poller.aclose()

        assert send_route.called
        # StubSTT default matn "Test ovozli xabar" javobga o'tadi
        assert b"Test ovozli xabar" in send_route.calls[0].request.content

    @respx.mock
    async def test_callback_query_acknowledges_and_replies(self, bot: ZetBot) -> None:
        answer_route = respx.post(f"{_BASE}/bot{_TOKEN}/answerCallbackQuery").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        send_route = respx.post(f"{_BASE}/bot{_TOKEN}/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        callback_update = {
            "update_id": 30,
            "callback_query": {
                "id": "cbq-1",
                "from": {"id": _OWNER_ID, "is_bot": False},
                "message": {
                    "message_id": 5,
                    "chat": {"id": _OWNER_ID, "type": "private"},
                },
                "data": "approve:r-abc",
            },
        }
        poller = TelegramPoller(token=_TOKEN, bot=bot)
        try:
            await poller._process_update(callback_update)
        finally:
            await poller.aclose()

        assert answer_route.called
        assert send_route.called


class TestModeration:
    """Kanal moderatsiyasi (Z51, #44) — faqat `moderated_chat_ids`da ishlaydi."""

    _MODERATED_CHAT_ID = -1001111111111

    @respx.mock
    async def test_other_bot_message_in_moderated_chat_is_deleted(self, bot: ZetBot) -> None:
        respx.post(f"{_BASE}/bot{_TOKEN}/getMe").mock(
            return_value=httpx.Response(200, json={"ok": True, "result": {"id": 555}})
        )
        delete_route = respx.post(f"{_BASE}/bot{_TOKEN}/deleteMessage").mock(
            return_value=httpx.Response(200, json={"ok": True, "result": True})
        )
        spam_update = {
            "update_id": 40,
            "message": {
                "message_id": 7,
                "from": {"id": 12345, "is_bot": True, "username": "some_ad_bot"},
                "chat": {"id": self._MODERATED_CHAT_ID, "type": "supergroup"},
                "text": "reklama",
            },
        }
        poller = TelegramPoller(
            token=_TOKEN, bot=bot, moderated_chat_ids=frozenset({self._MODERATED_CHAT_ID})
        )
        try:
            await poller._process_update(spam_update)
        finally:
            await poller.aclose()

        assert delete_route.called
        import json

        payload = json.loads(delete_route.calls[0].request.content)
        assert payload == {"chat_id": self._MODERATED_CHAT_ID, "message_id": 7}

    @respx.mock
    async def test_own_bot_message_in_moderated_chat_is_not_deleted(self, bot: ZetBot) -> None:
        respx.post(f"{_BASE}/bot{_TOKEN}/getMe").mock(
            return_value=httpx.Response(200, json={"ok": True, "result": {"id": 555}})
        )
        delete_route = respx.post(f"{_BASE}/bot{_TOKEN}/deleteMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        own_update = {
            "update_id": 41,
            "message": {
                "message_id": 8,
                "from": {"id": 555, "is_bot": True, "username": "our_own_bot"},
                "chat": {"id": self._MODERATED_CHAT_ID, "type": "supergroup"},
                "text": "e'lon",
            },
        }
        poller = TelegramPoller(
            token=_TOKEN, bot=bot, moderated_chat_ids=frozenset({self._MODERATED_CHAT_ID})
        )
        try:
            await poller._process_update(own_update)
        finally:
            await poller.aclose()

        assert not delete_route.called

    @respx.mock
    async def test_unmoderated_chat_is_never_touched(self, bot: ZetBot) -> None:
        """`moderated_chat_ids`da yo'q chat — begona bot bo'lsa ham tegilmaydi."""
        delete_route = respx.post(f"{_BASE}/bot{_TOKEN}/deleteMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        other_chat_update = {
            "update_id": 42,
            "message": {
                "message_id": 9,
                "from": {"id": 12345, "is_bot": True, "username": "some_ad_bot"},
                "chat": {"id": -1009999999999, "type": "supergroup"},
                "text": "reklama",
            },
        }
        poller = TelegramPoller(
            token=_TOKEN, bot=bot, moderated_chat_ids=frozenset({self._MODERATED_CHAT_ID})
        )
        try:
            await poller._process_update(other_chat_update)
        finally:
            await poller.aclose()

        assert not delete_route.called

    @respx.mock
    async def test_normal_message_in_moderated_chat_is_untouched(self, bot: ZetBot) -> None:
        respx.post(f"{_BASE}/bot{_TOKEN}/getMe").mock(
            return_value=httpx.Response(200, json={"ok": True, "result": {"id": 555}})
        )
        delete_route = respx.post(f"{_BASE}/bot{_TOKEN}/deleteMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        human_update = {
            "update_id": 43,
            "message": {
                "message_id": 10,
                "from": {"id": 777, "is_bot": False, "username": "haqiqiy_mijoz"},
                "chat": {"id": self._MODERATED_CHAT_ID, "type": "supergroup"},
                "text": "Mahsulot narxi qancha?",
            },
        }
        poller = TelegramPoller(
            token=_TOKEN, bot=bot, moderated_chat_ids=frozenset({self._MODERATED_CHAT_ID})
        )
        try:
            await poller._process_update(human_update)
        finally:
            await poller.aclose()

        assert not delete_route.called


class TestSendReplyVoiceFallback:
    """`voice_data` bo'lsa avval sendVoice, u rad etsa sendAudio'ga tushish.

    Real hisobda topilgan muammo (VOICE_MESSAGES_FORBIDDEN) uchun aynan
    shu naqsh yasalgan — polling doim ikkita yo'lga tayyor.
    """

    @respx.mock
    async def test_voice_forbidden_falls_back_to_audio(self, bot: ZetBot) -> None:
        respx.post(f"{_BASE}/bot{_TOKEN}/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        voice_route = respx.post(f"{_BASE}/bot{_TOKEN}/sendVoice").mock(
            return_value=httpx.Response(
                400, json={"ok": False, "description": "VOICE_MESSAGES_FORBIDDEN"}
            )
        )
        audio_route = respx.post(f"{_BASE}/bot{_TOKEN}/sendAudio").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )

        poller = TelegramPoller(token=_TOKEN, bot=bot)
        try:
            await poller._send_reply(
                chat_id=_OWNER_ID,
                output=TelegramOutput(text="ok", voice_data=b"MP3"),
            )
        finally:
            await poller.aclose()

        assert voice_route.called
        assert audio_route.called

    @respx.mock
    async def test_voice_ok_no_audio_fallback(self, bot: ZetBot) -> None:
        respx.post(f"{_BASE}/bot{_TOKEN}/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        voice_route = respx.post(f"{_BASE}/bot{_TOKEN}/sendVoice").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        audio_route = respx.post(f"{_BASE}/bot{_TOKEN}/sendAudio").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )

        poller = TelegramPoller(token=_TOKEN, bot=bot)
        try:
            await poller._send_reply(
                chat_id=_OWNER_ID,
                output=TelegramOutput(text="ok", voice_data=b"MP3"),
            )
        finally:
            await poller.aclose()

        assert voice_route.called
        assert not audio_route.called

    @respx.mock
    async def test_no_voice_data_only_text(self, bot: ZetBot) -> None:
        send_route = respx.post(f"{_BASE}/bot{_TOKEN}/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        voice_route = respx.post(f"{_BASE}/bot{_TOKEN}/sendVoice").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )

        poller = TelegramPoller(token=_TOKEN, bot=bot)
        try:
            await poller._send_reply(chat_id=_OWNER_ID, output=TelegramOutput(text="faqat matn"))
        finally:
            await poller.aclose()

        assert send_route.called
        assert not voice_route.called


class TestStopEndsLoop:
    """`run_forever()` haqiqiy loop — `stop()` chaqirilgach osilib qolmaydi.

    respx cheksiz mock berganda loop tez aylanadi; testda `stop()`ni
    birinchi `getUpdates`dan oldin chaqirib, `stop_event` `while` shartida
    darhol topilishini kafolatlaymiz.
    """

    @respx.mock
    async def test_stop_before_start_yields_immediately(self, bot: ZetBot) -> None:
        import asyncio

        # Umuman chaqirilishi kerak emas, lekin respx assert_all_called=True
        # default'ini oldini olish uchun ro'yxatga olamiz
        respx.get(f"{_BASE}/bot{_TOKEN}/getUpdates").mock(
            return_value=httpx.Response(200, json={"ok": True, "result": []})
        )
        poller = TelegramPoller(token=_TOKEN, bot=bot)
        poller.stop()  # stop() run_forever'dan avval — loop kirmaydi
        await asyncio.wait_for(poller.run_forever(), timeout=3)
        await poller.aclose()


class TestVoiceNoteFormat:
    """Ovozli javob Telegram'da MUSIQA emas, VOICE NOTE bo'lib chiqsin.

    BUG (ega ko'rgan): ovozli javoblar sarlavha/ijrochi maydonli audio
    pleyer bubble'ida chiqardi. Sabab — `_try_send_voice` TTS'dan kelgan
    **MP3** baytlarini `zet.ogg` nomi va `audio/mpeg` MIME bilan
    `sendVoice`ga berardi. Telegram `sendVoice` faqat OPUS bilan
    kodlangan OGG'ni voice note deb qabul qiladi.

    Bu klass ikkala tomonni ham qulflaydi: to'g'ri format `sendVoice`ga
    ketishi VA noto'g'ri format `sendVoice`ga UMUMAN berilmasligi.
    """

    @respx.mock
    async def test_ogg_goes_to_send_voice_with_correct_mime(self, bot: ZetBot) -> None:
        voice_route = respx.post(f"{_BASE}/bot{_TOKEN}/sendVoice").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        audio_route = respx.post(f"{_BASE}/bot{_TOKEN}/sendAudio").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        respx.post(f"{_BASE}/bot{_TOKEN}/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )

        poller = TelegramPoller(token=_TOKEN, bot=bot)
        try:
            await poller._send_reply(
                _OWNER_ID,
                TelegramOutput(text="javob", voice_data=b"OggS\x00opus", voice_format="ogg"),
            )
        finally:
            await poller.aclose()

        assert voice_route.called, "OGG/OPUS sendVoice'ga ketishi kerak edi"
        assert not audio_route.called, "sendVoice muvaffaqiyatli — sendAudio chaqirilmasin"

        body = voice_route.calls[0].request.content
        # ENG MUHIM DALIL: MIME `audio/ogg` (ilgari `audio/mpeg` edi —
        # aynan shu Telegram'ni musiqa deb o'ylashga majburlardi).
        assert b"audio/ogg" in body
        assert b"audio/mpeg" not in body
        assert b'name="voice"' in body

    @respx.mock
    async def test_mp3_never_sent_as_voice_note(self, bot: ZetBot) -> None:
        """MP3 `sendVoice`ga UMUMAN berilmaydi — halol `sendAudio`ga ketadi.

        Yolg'on "voice" da'vosi qilib, Telegram'ni musiqa ko'rsatishga
        majburlashdan ko'ra, ochiq audio fayl sifatida yuborish afzal."""
        voice_route = respx.post(f"{_BASE}/bot{_TOKEN}/sendVoice").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        audio_route = respx.post(f"{_BASE}/bot{_TOKEN}/sendAudio").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        respx.post(f"{_BASE}/bot{_TOKEN}/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )

        poller = TelegramPoller(token=_TOKEN, bot=bot)
        try:
            await poller._send_reply(
                _OWNER_ID,
                TelegramOutput(text="javob", voice_data=b"ID3mp3", voice_format="mp3"),
            )
        finally:
            await poller.aclose()

        assert not voice_route.called, "MP3 HECH QACHON sendVoice'ga berilmasligi kerak"
        assert audio_route.called

    @respx.mock
    async def test_send_voice_rejected_falls_back_to_audio(self, bot: ZetBot) -> None:
        """Foydalanuvchi voice message'ni bloklagan bo'lsa (400) — audio."""
        voice_route = respx.post(f"{_BASE}/bot{_TOKEN}/sendVoice").mock(
            return_value=httpx.Response(
                400, json={"ok": False, "description": "VOICE_MESSAGES_FORBIDDEN"}
            )
        )
        audio_route = respx.post(f"{_BASE}/bot{_TOKEN}/sendAudio").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        respx.post(f"{_BASE}/bot{_TOKEN}/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )

        poller = TelegramPoller(token=_TOKEN, bot=bot)
        try:
            await poller._send_reply(
                _OWNER_ID,
                TelegramOutput(text="javob", voice_data=b"OggS\x00opus", voice_format="ogg"),
            )
        finally:
            await poller.aclose()

        assert voice_route.called
        assert audio_route.called
        # Fallback ham OGG sifatida ketadi (MP3 deb yolg'on nom bermaymiz)
        assert b"audio/ogg" in audio_route.calls[0].request.content
