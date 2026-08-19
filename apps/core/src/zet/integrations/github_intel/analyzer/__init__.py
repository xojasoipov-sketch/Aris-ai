"""GitHub Intelligence — repository analyzer (spec Bo'lim 5)."""

from __future__ import annotations

from zet.integrations.github_intel.analyzer.repository_analyzer import (
    RepositoryAnalysis,
    RequestFn,
    analyze_repository,
)

__all__ = ["RepositoryAnalysis", "RequestFn", "analyze_repository"]
