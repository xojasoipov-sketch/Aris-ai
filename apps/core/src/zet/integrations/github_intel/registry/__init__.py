"""GitHub Intelligence — manba registri (Source Registry, spec Bo'lim 2/3)."""

from __future__ import annotations

from zet.integrations.github_intel.registry.models import (
    KnowledgeSource,
    SourceCategory,
    SourceType,
    TrustLevel,
    source_id,
)
from zet.integrations.github_intel.registry.repository import SourceRegistry
from zet.integrations.github_intel.registry.seed import builtin_sources

__all__ = [
    "KnowledgeSource",
    "SourceCategory",
    "SourceRegistry",
    "SourceType",
    "TrustLevel",
    "builtin_sources",
    "source_id",
]
