"""api/deps.get_notifier() tanlash mantiqi — real vs stub."""

from __future__ import annotations

import pytest

from zet.api import deps as api_deps
from zet.config import get_settings
from zet.telegram.http_notifier import TelegramNotifier
from zet.telegram.notifier import StubNotifier


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    """Har test o'z holatidan boshlaydi (lru_cache singleton'lar tozalanadi)."""
    get_settings.cache_clear()
    api_deps.get_notifier.cache_clear()
    yield
    get_settings.cache_clear()
    api_deps.get_notifier.cache_clear()


class TestGetNotifier:
    def test_stub_when_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ZET_TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("ZET_TELEGRAM_OWNER_IDS", raising=False)
        notifier = api_deps.get_notifier()
        assert isinstance(notifier, StubNotifier)

    def test_stub_when_only_token_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ZET_TELEGRAM_BOT_TOKEN", "123:ABC")
        monkeypatch.delenv("ZET_TELEGRAM_OWNER_IDS", raising=False)
        notifier = api_deps.get_notifier()
        assert isinstance(notifier, StubNotifier)

    def test_real_notifier_when_fully_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ZET_TELEGRAM_BOT_TOKEN", "123:ABC")
        monkeypatch.setenv("ZET_TELEGRAM_OWNER_IDS", "999")
        notifier = api_deps.get_notifier()
        assert isinstance(notifier, TelegramNotifier)
        assert notifier.is_configured is True
