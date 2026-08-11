"""FastAPI dependency'lari (Z1.14).

Singleton va per-request dependency'lar.
"""

from __future__ import annotations

from functools import lru_cache

from zet.config import Settings, get_settings
from zet.memory.store import MemoryStore
from zet.security.killswitch import KillSwitchState


@lru_cache(maxsize=1)
def get_killswitch() -> KillSwitchState:
    """Global killswitch holati (singleton)."""
    return KillSwitchState()


@lru_cache(maxsize=1)
def get_memory_store() -> MemoryStore:
    """Global in-memory xotira do'koni (singleton).

    Produksiyada PgMemoryStore bilan almashtiriladi.
    """
    return MemoryStore()


def get_config() -> Settings:
    """Konfiguratsiya."""
    return get_settings()
