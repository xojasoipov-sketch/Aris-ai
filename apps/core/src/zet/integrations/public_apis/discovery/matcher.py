"""Capability → ijro etiladigan (ENABLED) provayderlar — zaxira tanlovi
uchun (Bo'lim 14).

`ModelRouter.candidates_for(task_class)`ning bir xil naqshi
(`zet/llm/catalog.py`) — statik ustuvorlik ro'yxati, sog'liq bo'yicha
saralangan, birinchi ISHLAYDIGANI tanlanadi. Faqat `status=ENABLED`
yozuvlar qaytariladi — DISCOVERED/EVALUATED yozuvlar hali ijro
etilmaydigan, faqat kashfiyot uchun (Bo'lim 22).
"""

from __future__ import annotations

from zet.integrations.public_apis.catalog.models import APIStatus, PublicAPIEntry


def enabled_providers_for_capability(
    entries: list[PublicAPIEntry], capability: str
) -> list[PublicAPIEntry]:
    """Berilgan capability uchun ENABLED yozuvlarni sog'liq bo'yicha
    saralab qaytaradi — birinchisi asosiy, qolganlari zaxira.

    Sog'liq noma'lum (`None`) yozuvlar — na eng yaxshi, na eng yomon
    (0.5 neytral bilan saralanadi), chunki hali tekshirilmaganlik
    "sog'lom emas" degani emas.
    """
    tag = capability.strip().lower()
    candidates = [
        e
        for e in entries
        if e.status is APIStatus.ENABLED and tag in {c.lower() for c in e.capabilities}
    ]
    return sorted(
        candidates,
        key=lambda e: e.health_score if e.health_score is not None else 0.5,
        reverse=True,
    )


__all__ = ["enabled_providers_for_capability"]
