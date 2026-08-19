"""Provayder sog'lik kuzatuvi — HAQIQIY chaqiruvlardan passiv yozib
borish (Bo'lim 13).

Faol/rejalashtirilgan tekshiruv (background health-check job) ushbu
bosqichda YO'Q — `docs/audits/PUBLIC_APIS_INTEGRATION_FINAL.md`da
ochiq "NOT IMPLEMENTED" deb belgilangan; har bir adapter chaqirilganda
o'zi natijasini shu yerga yozadi (`PublicAPIAdapter` bazaviy klassiga
qarang), bu yetarli signal beradi ammo hech kim chaqirmagan provayder
"sog'lom" ham, "kasal" ham emas — `None` (neytral)."""

from __future__ import annotations

from zet.integrations.public_apis.health.scoring import HealthSnapshot, ProviderHealthTracker

__all__ = ["HealthSnapshot", "ProviderHealthTracker"]
