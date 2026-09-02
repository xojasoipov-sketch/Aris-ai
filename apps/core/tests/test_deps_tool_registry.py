"""api/deps.get_tool_registry() — production registry sozlamalari."""

from __future__ import annotations

import pytest

from zet.api import deps as api_deps
from zet.config import get_settings


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    get_settings.cache_clear()
    api_deps.get_tool_registry.cache_clear()
    yield
    get_settings.cache_clear()
    api_deps.get_tool_registry.cache_clear()


class TestGetToolRegistry:
    def test_web_read_is_not_stub_by_default(self) -> None:
        """gap-analysis #12: web.read ilgari doim stub edi — endi real."""
        registry = api_deps.get_tool_registry()
        tool = registry.get("web.read")
        assert tool._stub is False

    def test_github_stub_without_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ZET_GITHUB_TOKEN", raising=False)
        registry = api_deps.get_tool_registry()
        tool = registry.get("github.read")
        assert tool.is_real is False

    def test_github_real_with_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ZET_GITHUB_TOKEN", "ghp_test")
        registry = api_deps.get_tool_registry()
        tool = registry.get("github.read")
        assert tool.is_real is True

    def test_web_search_stub_without_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ZET_WEB_SEARCH_API_KEY", raising=False)
        registry = api_deps.get_tool_registry()
        tool = registry.get("web.search")
        assert tool.is_real is False

    def test_web_search_real_with_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ZET_WEB_SEARCH_API_KEY", "brave_test")
        registry = api_deps.get_tool_registry()
        tool = registry.get("web.search")
        assert tool.is_real is True

    def test_shell_disabled_by_default(self) -> None:
        registry = api_deps.get_tool_registry()
        assert not registry.has("shell.exec")
