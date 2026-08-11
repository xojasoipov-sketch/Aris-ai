"""Audit Log — o'zgarmas xavfsizlik jurnali (Bo'lim 11).

Append-only log: yozilgan yozuvni o'zgartirib yoki o'chirib bo'lmaydi.
Har bir amal — kim, nima, qachon, natija — yozib boriladi.

Audit turlari:
    - AUTH — autentifikatsiya (login, token yaratish)
    - PERMISSION — ruxsat tekshiruvi
    - DATA — ma'lumot o'zgarishi
    - CONFIG — sozlama o'zgarishi
    - SECURITY — xavfsizlik hodisasi (injection, brute force)
    - SYSTEM — tizim hodisasi (start, stop, killswitch)

Xavfsizlik:
    - Append-only: faqat qo'shish, o'chirish/o'zgartirish yo'q
    - Har bir yozuv — frozen (o'zgarmas)
    - Hash chain (har bir yozuv oldingi yozuv hashini o'z ichiga oladi)
    - Produksiyada: fayl + DB + tashqi saqlash (S3/B2)

Bog'liq qarorlar:
    Bo'lim 11 — xavfsizlik
    V-33 — audit log immutability
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)


class AuditCategory(StrEnum):
    """Audit hodisa turi."""

    AUTH = "auth"
    """Autentifikatsiya."""

    PERMISSION = "permission"
    """Ruxsat tekshiruvi."""

    DATA = "data"
    """Ma'lumot o'zgarishi."""

    CONFIG = "config"
    """Sozlama o'zgarishi."""

    SECURITY = "security"
    """Xavfsizlik hodisasi."""

    SYSTEM = "system"
    """Tizim hodisasi."""


class AuditEntry(BaseModel, frozen=True):
    """Bitta audit yozuvi — o'zgarmas.

    Hash chain: har bir yozuv oldingi yozuvning hashini saqlaydi.
    Bu zanjir buzilsa — ma'lumot o'zgartirilgan.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    """Unikal yozuv ID."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Hodisa vaqti."""

    category: AuditCategory
    """Hodisa turi."""

    action: str
    """Amal nomi (masalan: 'login', 'tool.execute', 'killswitch.engage')."""

    actor: str = "system"
    """Kim bajardi (owner, system, agent_name)."""

    target: str = ""
    """Nima ustida (run_id, tool_name, agent_name)."""

    detail: str = ""
    """Qo'shimcha ma'lumot."""

    success: bool = True
    """Amal muvaffaqiyatlimi."""

    prev_hash: str = ""
    """Oldingi yozuv hashi (hash chain)."""

    def compute_hash(self) -> str:
        """Bu yozuvning hashini hisoblash.

        SHA-256 hash — vaqt + kategori + amal + actor + target + oldingi hash.
        """
        data = (
            f"{self.id}:{self.timestamp.isoformat()}"
            f":{self.category}:{self.action}"
            f":{self.actor}:{self.target}"
            f":{self.success}:{self.prev_hash}"
        )
        return hashlib.sha256(data.encode()).hexdigest()[:32]


class AuditLog:
    """Append-only audit log — o'zgarmas xavfsizlik jurnali.

    Asosiy xususiyatlar:
        - Faqat qo'shish (append) mumkin
        - O'chirish/o'zgartirish mumkin emas
        - Hash chain yordamida yaxlitlik tekshiriladi
    """

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []
        self._last_hash: str = ""

    def append(
        self,
        *,
        category: AuditCategory,
        action: str,
        actor: str = "system",
        target: str = "",
        detail: str = "",
        success: bool = True,
    ) -> AuditEntry:
        """Yangi yozuv qo'shish.

        Args:
            category: Hodisa turi
            action: Amal nomi
            actor: Kim bajardi
            target: Nima ustida
            detail: Qo'shimcha ma'lumot
            success: Muvaffaqiyatlimi

        Returns:
            Yaratilgan AuditEntry
        """
        entry = AuditEntry(
            category=category,
            action=action,
            actor=actor,
            target=target,
            detail=detail,
            success=success,
            prev_hash=self._last_hash,
        )
        self._last_hash = entry.compute_hash()
        self._entries.append(entry)

        log.info(
            "audit.entry",
            category=category.value,
            action=action,
            actor=actor,
            success=success,
        )
        return entry

    def entries(
        self,
        *,
        category: AuditCategory | None = None,
        actor: str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Yozuvlarni filtrlash.

        Args:
            category: Kategoriya bo'yicha filtr
            actor: Actor bo'yicha filtr
            limit: Maksimal natijalar soni

        Returns:
            Filtrlangan yozuvlar (yangilardan eskigacha)
        """
        result = reversed(self._entries)
        if category is not None:
            result = (e for e in result if e.category == category)
        if actor is not None:
            result = (e for e in result if e.actor == actor)
        return list(result)[:limit]

    def verify_integrity(self) -> bool:
        """Hash chain yaxlitligini tekshirish.

        Har bir yozuvning prev_hash oldingi yozuvning hisoblangan
        hashiga mos kelishi kerak. Agar moslik buzilgan bo'lsa —
        ma'lumot o'zgartirilgan.

        Returns:
            True agar butun zanjir yaxlit bo'lsa
        """
        prev_hash = ""
        for entry in self._entries:
            if entry.prev_hash != prev_hash:
                log.critical(
                    "audit.integrity_violation",
                    entry_id=entry.id,
                    expected_hash=prev_hash,
                    actual_hash=entry.prev_hash,
                )
                return False
            prev_hash = entry.compute_hash()
        return True

    @property
    def count(self) -> int:
        """Jami yozuvlar soni."""
        return len(self._entries)

    @property
    def last_entry(self) -> AuditEntry | None:
        """Oxirgi yozuv."""
        return self._entries[-1] if self._entries else None

    @property
    def stats(self) -> dict[str, Any]:
        """Statistika."""
        entries = self._entries
        by_category: dict[str, int] = {}
        for e in entries:
            by_category[e.category.value] = by_category.get(e.category.value, 0) + 1
        return {
            "total": len(entries),
            "by_category": by_category,
            "failed": sum(1 for e in entries if not e.success),
            "integrity_ok": self.verify_integrity(),
        }
