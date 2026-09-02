"""Xotira yozish siyosati (Bo'lim 2).

Qoidalar:
    - Har bir qatlam uchun ruxsat etilgan trust_level'lar belgilangan
    - OWNER — barcha qatlamlarga yozishi mumkin
    - SYSTEM — personal va knowledge dan tashqari
    - UNTRUSTED — faqat short_term
    - Yozuvning trust_level manba ishonchliligiga mos bo'lishi kerak

Bog'liq qarorlar:
    V-14 — ruxsatga bog'liq ko'rinish
    A-05 — ishonch darajalari
"""

from __future__ import annotations

from zet.domain.memory import MemoryLayer

# Qaysi trust_level qaysi qatlamlarga yozishi mumkin
WRITE_POLICY: dict[str, frozenset[MemoryLayer]] = {
    "owner": frozenset(MemoryLayer),  # barchasi
    "system": frozenset(
        {
            MemoryLayer.SHORT_TERM,
            MemoryLayer.CONVERSATION,
            MemoryLayer.TASK,
            MemoryLayer.PROJECT,
            MemoryLayer.BUSINESS,
        }
    ),
    "untrusted": frozenset(
        {
            MemoryLayer.SHORT_TERM,
        }
    ),
}

# Qaysi trust_level qaysi qatlamlarni o'qishi mumkin
READ_POLICY: dict[str, frozenset[MemoryLayer]] = {
    "owner": frozenset(MemoryLayer),
    "system": frozenset(
        {
            MemoryLayer.SHORT_TERM,
            MemoryLayer.CONVERSATION,
            MemoryLayer.TASK,
            MemoryLayer.PROJECT,
            MemoryLayer.BUSINESS,
            MemoryLayer.KNOWLEDGE,
        }
    ),
    "untrusted": frozenset(
        {
            MemoryLayer.SHORT_TERM,
            MemoryLayer.KNOWLEDGE,  # faqat o'qish
        }
    ),
}


class MemoryPolicyError(Exception):
    """Xotira siyosati buzilganda."""

    def __init__(self, trust_level: str, layer: MemoryLayer, action: str = "write") -> None:
        self.trust_level = trust_level
        self.layer = layer
        self.action = action
        super().__init__(f"{trust_level} darajasi {layer.value} qatlamiga {action} qila olmaydi")


def check_write(trust_level: str, layer: MemoryLayer) -> None:
    """Yozish ruxsatini tekshirish.

    Raises:
        MemoryPolicyError: Agar ruxsat bo'lmasa.
    """
    allowed = WRITE_POLICY.get(trust_level, frozenset())
    if layer not in allowed:
        raise MemoryPolicyError(trust_level, layer, "write")


def check_read(trust_level: str, layer: MemoryLayer) -> None:
    """O'qish ruxsatini tekshirish.

    Raises:
        MemoryPolicyError: Agar ruxsat bo'lmasa.
    """
    allowed = READ_POLICY.get(trust_level, frozenset())
    if layer not in allowed:
        raise MemoryPolicyError(trust_level, layer, "read")


def can_write(trust_level: str, layer: MemoryLayer) -> bool:
    """Yozish mumkinmi (exception o'rniga bool)."""
    allowed = WRITE_POLICY.get(trust_level, frozenset())
    return layer in allowed


def can_read(trust_level: str, layer: MemoryLayer) -> bool:
    """O'qish mumkinmi (exception o'rniga bool)."""
    allowed = READ_POLICY.get(trust_level, frozenset())
    return layer in allowed


def writable_layers(trust_level: str) -> frozenset[MemoryLayer]:
    """Berilgan trust_level uchun yozish mumkin qatlamlar."""
    return WRITE_POLICY.get(trust_level, frozenset())


def readable_layers(trust_level: str) -> frozenset[MemoryLayer]:
    """Berilgan trust_level uchun o'qish mumkin qatlamlar."""
    return READ_POLICY.get(trust_level, frozenset())
