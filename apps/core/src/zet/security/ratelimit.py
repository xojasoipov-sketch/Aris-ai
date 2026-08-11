"""Rate Limiter — so'rovlar chastotasini cheklash (Bo'lim 11).

Sliding window asosida rate limiting.
Har bir kalit (user, IP, agent) uchun alohida hisoblagich.

Algoritmlar:
    - Fixed window: vaqt oynasi ichida ruxsat berilgan so'rovlar soni
    - Oddiy va samarali — Ko'pgina holatlar uchun yetarli

Xavfsizlik:
    - Default: 60 so'rov/minutda (OWNER uchun)
    - Agent: 30 so'rov/minutda
    - UNTRUSTED: 10 so'rov/minutda
    - Cheklovni oshirish mumkin emas (faqat kamaytirish)

Bog'liq qarorlar:
    Bo'lim 11 — xavfsizlik
    A-05 — trust level chegaralari
    A-07 — tormozlar
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

import structlog

log = structlog.get_logger(__name__)


class RateLimitTier(StrEnum):
    """Cheklash darajasi."""

    OWNER = "owner"
    """Ega — eng yuqori limit."""

    SYSTEM = "system"
    """Tizim agentlari — o'rta limit."""

    UNTRUSTED = "untrusted"
    """Ishonchsiz — eng past limit."""


# Default limitlar (so'rov/minutda)
DEFAULT_LIMITS: dict[RateLimitTier, int] = {
    RateLimitTier.OWNER: 60,
    RateLimitTier.SYSTEM: 30,
    RateLimitTier.UNTRUSTED: 10,
}


@dataclass(frozen=True)
class RateLimitResult:
    """Rate limit tekshiruvi natijasi."""

    allowed: bool
    """So'rovga ruxsat berildi."""

    remaining: int
    """Qolgan so'rovlar soni."""

    limit: int
    """Umumiy limit."""

    reset_at: float
    """Keyingi reset vaqti (epoch seconds)."""

    retry_after: float = 0.0
    """Kutish kerak bo'lgan vaqt (sekundda)."""


@dataclass
class _Window:
    """Bitta kalit uchun fixed window."""

    count: int = 0
    window_start: float = field(default_factory=time.monotonic)


class RateLimiter:
    """Fixed window rate limiter.

    Har bir kalit (user_id, agent_name, IP va h.k.) uchun
    belgilangan vaqt oynasi ichida so'rovlar sonini cheklaydi.
    """

    def __init__(
        self,
        *,
        window_s: int = 60,
        default_limits: dict[RateLimitTier, int] | None = None,
    ) -> None:
        """
        Args:
            window_s: Vaqt oynasi (sekundda). Default: 60
            default_limits: Tier bo'yicha limitlar
        """
        self._window_s = window_s
        self._limits = default_limits if default_limits is not None else dict(DEFAULT_LIMITS)
        self._windows: dict[str, _Window] = {}
        self._custom_limits: dict[str, int] = {}
        self._total_allowed: int = 0
        self._total_denied: int = 0

    def check(
        self,
        key: str,
        tier: RateLimitTier = RateLimitTier.OWNER,
        *,
        cost: int = 1,
    ) -> RateLimitResult:
        """So'rovni tekshirish va hisobga olish.

        Args:
            key: Kalit (user_id, agent_name, IP)
            tier: Trust darajasi
            cost: So'rov "og'irligi" (default: 1)

        Returns:
            RateLimitResult
        """
        now = time.monotonic()
        limit = self._custom_limits.get(key, self._limits.get(tier, 60))

        window = self._windows.get(key)
        if window is None or (now - window.window_start) >= self._window_s:
            # Yangi oyna
            window = _Window(count=0, window_start=now)
            self._windows[key] = window

        reset_at = window.window_start + self._window_s

        if window.count + cost <= limit:
            window.count += cost
            self._total_allowed += 1
            return RateLimitResult(
                allowed=True,
                remaining=limit - window.count,
                limit=limit,
                reset_at=reset_at,
            )

        self._total_denied += 1
        retry_after = reset_at - now
        log.warning(
            "ratelimit.exceeded",
            key=key,
            tier=tier.value,
            count=window.count,
            limit=limit,
        )
        return RateLimitResult(
            allowed=False,
            remaining=0,
            limit=limit,
            reset_at=reset_at,
            retry_after=max(0.0, retry_after),
        )

    def set_custom_limit(self, key: str, limit: int) -> None:
        """Bitta kalit uchun maxsus limit o'rnatish.

        Args:
            key: Kalit
            limit: Yangi limit (so'rov/oyna)
        """
        self._custom_limits[key] = limit

    def remove_custom_limit(self, key: str) -> bool:
        """Maxsus limitni olib tashlash.

        Returns:
            True agar mavjud bo'lsa va olib tashlansa
        """
        if key in self._custom_limits:
            del self._custom_limits[key]
            return True
        return False

    def reset(self, key: str) -> bool:
        """Bitta kalit uchun hisoblagichni tozalash.

        Returns:
            True agar mavjud bo'lsa va tozalansa
        """
        if key in self._windows:
            del self._windows[key]
            return True
        return False

    def reset_all(self) -> int:
        """Barcha hisoblagichlarni tozalash.

        Returns:
            Tozalangan kalitlar soni
        """
        count = len(self._windows)
        self._windows.clear()
        return count

    @property
    def stats(self) -> dict[str, int]:
        """Statistika."""
        return {
            "active_windows": len(self._windows),
            "custom_limits": len(self._custom_limits),
            "total_allowed": self._total_allowed,
            "total_denied": self._total_denied,
        }
