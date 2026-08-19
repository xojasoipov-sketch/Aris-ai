"""Katalog saqlash joyi — jarayon-xotirasida, `TTLCache` bilan bir xil
oddiylik falsafasi (`zet/feeds/providers.py`dagi izohga qarang: qo'shimcha
tashqi bog'liqlik — Redis/DB — bu ma'lumot uchun foyda emas, chunki
u istalgan vaqt qayta sinxronlanishi mumkin).

MUHIM: `replace_all()` (yangi sync) descriptiv maydonlarni (nom, tavsif,
auth, https, cors) YANGILAYDI, lekin BAHOLASH maydonlarini (`status`,
`trust_score`, `health_score`, `capabilities`) MAVJUD yozuv uchun
SAQLAB QOLADI — aks holda har sync operatorning "bu ENABLED" qarorini
"DISCOVERED"ga qaytarib qo'yardi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from zet.integrations.public_apis.catalog.models import APIStatus, PublicAPIEntry


@dataclass(frozen=True, slots=True)
class SyncReport:
    """Bitta sync urinishining natijasi — halol, kompyuter tomonidan
    tekshiriladigan sonlar (Bo'lim 3: "sync report")."""

    synced_at: datetime
    source_url: str
    total_entries: int
    added: int
    removed: int
    changed: int
    categories: int
    ok: bool
    error: str | None = None


class CatalogRepository:
    """Normallashtirilgan `PublicAPIEntry` yozuvlarining yagona saqlanish
    joyi. Discovery/health shu yerdan o'qiydi; `ToolRegistry` bu klassni
    UMUMAN bilmaydi — faqat ENABLED bo'lgan, qo'lda yozilgan adapterlar
    ro'yxatga olinadi (katalog va ijro qat'iy ajratilgan, Bo'lim 22)."""

    def __init__(self) -> None:
        self._entries: dict[str, PublicAPIEntry] = {}
        self._last_sync: SyncReport | None = None

    def all(self) -> list[PublicAPIEntry]:
        return list(self._entries.values())

    def get(self, entry_id: str) -> PublicAPIEntry | None:
        return self._entries.get(entry_id)

    def by_category(self, category: str) -> list[PublicAPIEntry]:
        low = category.strip().lower()
        return [e for e in self._entries.values() if e.category.lower() == low]

    def categories(self) -> list[str]:
        return sorted({e.category for e in self._entries.values()})

    def by_status(self, status: APIStatus) -> list[PublicAPIEntry]:
        return [e for e in self._entries.values() if e.status is status]

    @property
    def last_sync(self) -> SyncReport | None:
        return self._last_sync

    def replace_all(
        self, fresh_entries: list[PublicAPIEntry], *, source_url: str, now: datetime
    ) -> SyncReport:
        """Yangi sync natijasini joriy katalogga BIRLASHTIRADI (o'rniga
        qo'ymaydi) — mavjud yozuvlarning baholash maydonlari saqlanadi."""
        fresh_by_id = {e.id: e for e in fresh_entries}

        added = 0
        changed = 0
        merged: dict[str, PublicAPIEntry] = {}

        for entry_id, fresh in fresh_by_id.items():
            existing = self._entries.get(entry_id)
            if existing is None:
                added += 1
                merged[entry_id] = fresh
                continue
            # Mavjud — descriptiv maydonlarni yangilaymiz, baholovni saqlaymiz.
            import dataclasses

            merged_entry = dataclasses.replace(
                fresh,
                status=existing.status,
                trust_score=existing.trust_score,
                health_score=existing.health_score,
                last_checked=existing.last_checked,
                capabilities=existing.capabilities,
            )
            if merged_entry != existing:
                changed += 1
            merged[entry_id] = merged_entry

        removed = len(set(self._entries) - set(fresh_by_id))

        self._entries = merged
        report = SyncReport(
            synced_at=now,
            source_url=source_url,
            total_entries=len(merged),
            added=added,
            removed=removed,
            changed=changed,
            categories=len({e.category for e in merged.values()}),
            ok=True,
        )
        self._last_sync = report
        return report

    def record_failed_sync(self, *, source_url: str, now: datetime, error: str) -> SyncReport:
        """Sync muvaffaqiyatsiz bo'lganda — katalog O'ZGARISHSIZ qoladi,
        faqat xato hisobotga yoziladi (eski, ishlaydigan katalog
        yo'qolib qolmasligi kerak — Bo'lim 3 ruhida, `FeedError`
        falsafasi bilan bir xil: yolg'on ma'lumot yaxshiroqdan ko'ra
        ochiq xato yaxshiroq)."""
        report = SyncReport(
            synced_at=now,
            source_url=source_url,
            total_entries=len(self._entries),
            added=0,
            removed=0,
            changed=0,
            categories=len({e.category for e in self._entries.values()}),
            ok=False,
            error=error,
        )
        self._last_sync = report
        return report

    def mark_status(self, entry_id: str, status: APIStatus) -> PublicAPIEntry | None:
        """Operator/audit qarori — yozuvni ENABLED/REJECTED/DISABLED
        deb belgilaydi. Katalogda yo'q ID uchun `None`."""
        entry = self._entries.get(entry_id)
        if entry is None:
            return None
        updated = entry.with_status(status)
        self._entries[entry_id] = updated
        return updated

    def set_capabilities(self, entry_id: str, capabilities: tuple[str, ...]) -> PublicAPIEntry | None:
        entry = self._entries.get(entry_id)
        if entry is None:
            return None
        updated = entry.with_capabilities(capabilities)
        self._entries[entry_id] = updated
        return updated

    def set_health(
        self, entry_id: str, *, health_score: float, checked_at: datetime
    ) -> PublicAPIEntry | None:
        entry = self._entries.get(entry_id)
        if entry is None:
            return None
        updated = entry.with_health(health_score=health_score, last_checked=checked_at)
        self._entries[entry_id] = updated
        return updated


__all__ = ["CatalogRepository", "SyncReport"]
