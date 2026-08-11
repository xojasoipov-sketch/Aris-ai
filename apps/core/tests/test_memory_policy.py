"""Bo'lim 2 — Memory siyosat testlari.

Tekshiriladi:
    - Owner barcha qatlamlarga yozishi mumkin
    - System personal/knowledge ga yoza olmaydi
    - Untrusted faqat short_term ga yozishi mumkin
    - O'qish siyosati
    - Yordamchi funksiyalar
"""

from __future__ import annotations

import pytest

from zet.domain.memory import MemoryLayer
from zet.memory.policy import (
    MemoryPolicyError,
    can_read,
    can_write,
    check_read,
    check_write,
    readable_layers,
    writable_layers,
)


class TestWritePolicy:
    def test_owner_can_write_all(self) -> None:
        """Owner barcha qatlamlarga yozishi mumkin."""
        for layer in MemoryLayer:
            check_write("owner", layer)  # hech qanday exception bo'lmasligi kerak

    def test_system_can_write_allowed(self) -> None:
        """System ruxsat etilgan qatlamlarga yozishi mumkin."""
        for layer in [
            MemoryLayer.SHORT_TERM,
            MemoryLayer.CONVERSATION,
            MemoryLayer.TASK,
            MemoryLayer.PROJECT,
            MemoryLayer.BUSINESS,
        ]:
            check_write("system", layer)

    def test_system_cannot_write_personal(self) -> None:
        """System personal qatlamiga yoza olmaydi."""
        with pytest.raises(MemoryPolicyError):
            check_write("system", MemoryLayer.PERSONAL)

    def test_system_cannot_write_knowledge(self) -> None:
        """System knowledge qatlamiga yoza olmaydi."""
        with pytest.raises(MemoryPolicyError):
            check_write("system", MemoryLayer.KNOWLEDGE)

    def test_untrusted_can_write_short_term(self) -> None:
        """Untrusted faqat short_term ga yozishi mumkin."""
        check_write("untrusted", MemoryLayer.SHORT_TERM)

    def test_untrusted_cannot_write_knowledge(self) -> None:
        """Untrusted knowledge ga yoza olmaydi."""
        with pytest.raises(MemoryPolicyError):
            check_write("untrusted", MemoryLayer.KNOWLEDGE)

    def test_untrusted_cannot_write_conversation(self) -> None:
        """Untrusted conversation ga yoza olmaydi."""
        with pytest.raises(MemoryPolicyError):
            check_write("untrusted", MemoryLayer.CONVERSATION)

    def test_unknown_trust_level(self) -> None:
        """Noma'lum trust_level — hech narsa yoza olmaydi."""
        with pytest.raises(MemoryPolicyError):
            check_write("unknown", MemoryLayer.SHORT_TERM)


class TestReadPolicy:
    def test_owner_can_read_all(self) -> None:
        """Owner barcha qatlamlarni o'qishi mumkin."""
        for layer in MemoryLayer:
            check_read("owner", layer)

    def test_system_can_read_most(self) -> None:
        """System personal dan tashqari o'qishi mumkin."""
        for layer in [
            MemoryLayer.SHORT_TERM,
            MemoryLayer.CONVERSATION,
            MemoryLayer.TASK,
            MemoryLayer.PROJECT,
            MemoryLayer.BUSINESS,
            MemoryLayer.KNOWLEDGE,
        ]:
            check_read("system", layer)

    def test_system_cannot_read_personal(self) -> None:
        """System personal qatlamini o'qiy olmaydi."""
        with pytest.raises(MemoryPolicyError):
            check_read("system", MemoryLayer.PERSONAL)

    def test_untrusted_can_read_short_term(self) -> None:
        """Untrusted short_term ni o'qishi mumkin."""
        check_read("untrusted", MemoryLayer.SHORT_TERM)

    def test_untrusted_can_read_knowledge(self) -> None:
        """Untrusted knowledge ni o'qishi mumkin (faqat o'qish)."""
        check_read("untrusted", MemoryLayer.KNOWLEDGE)

    def test_untrusted_cannot_read_personal(self) -> None:
        """Untrusted personal ni o'qiy olmaydi."""
        with pytest.raises(MemoryPolicyError):
            check_read("untrusted", MemoryLayer.PERSONAL)


class TestHelpers:
    def test_can_write_bool(self) -> None:
        """can_write bool qaytaradi."""
        assert can_write("owner", MemoryLayer.KNOWLEDGE) is True
        assert can_write("untrusted", MemoryLayer.KNOWLEDGE) is False

    def test_can_read_bool(self) -> None:
        """can_read bool qaytaradi."""
        assert can_read("system", MemoryLayer.KNOWLEDGE) is True
        assert can_read("system", MemoryLayer.PERSONAL) is False

    def test_writable_layers(self) -> None:
        """writable_layers to'g'ri qaytaradi."""
        layers = writable_layers("untrusted")
        assert layers == frozenset({MemoryLayer.SHORT_TERM})

    def test_readable_layers(self) -> None:
        """readable_layers to'g'ri qaytaradi."""
        layers = readable_layers("owner")
        assert layers == frozenset(MemoryLayer)

    def test_policy_error_message(self) -> None:
        """MemoryPolicyError xabar formati."""
        err = MemoryPolicyError("untrusted", MemoryLayer.KNOWLEDGE, "write")
        assert "untrusted" in str(err)
        assert "knowledge" in str(err)
        assert "write" in str(err)

    def test_unknown_returns_empty(self) -> None:
        """Noma'lum trust_level uchun bo'sh set."""
        assert writable_layers("alien") == frozenset()
        assert readable_layers("alien") == frozenset()
