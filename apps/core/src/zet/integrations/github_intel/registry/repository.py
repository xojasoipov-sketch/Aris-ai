"""Manba registrining saqlash joyi — jarayon-xotirasida (`CatalogRepository`
bilan bir xil oddiylik falsafasi, `public_apis/catalog/repository.py`).

MUHIM FARQ: bu yerda 1500+ avtomatik-parse qilingan yozuv EMAS — atigi
bir nechta (hozircha 10: 9 ta audit qilingan repo + public-apis o'zi),
QO'LDA yozilgan (`seed.py`) va operator tomonidan qo'lda kengaytiriladi.
Shuning uchun `CatalogRepository.replace_all()`ning "sync bilan
birlashtirish" murakkabligi shart emas — oddiy `register()` yetarli.
"""

from __future__ import annotations

from zet.integrations.github_intel.registry.models import (
    KnowledgeSource,
    SourceCategory,
    TrustLevel,
)


class SourceRegistry:
    """`KnowledgeSource` yozuvlarining yagona saqlanish joyi."""

    def __init__(self) -> None:
        self._sources: dict[str, KnowledgeSource] = {}

    def register(self, source: KnowledgeSource) -> None:
        self._sources[source.id] = source

    def register_many(self, sources: list[KnowledgeSource]) -> None:
        for source in sources:
            self.register(source)

    def get(self, source_id: str) -> KnowledgeSource | None:
        return self._sources.get(source_id)

    def get_by_repository(self, repository: str) -> KnowledgeSource | None:
        low = repository.strip().lower()
        for source in self._sources.values():
            if source.repository.strip().lower() == low:
                return source
        return None

    def all(self) -> list[KnowledgeSource]:
        return list(self._sources.values())

    def by_category(self, category: SourceCategory) -> list[KnowledgeSource]:
        return [s for s in self._sources.values() if s.category is category]

    def by_trust_level(self, trust_level: TrustLevel) -> list[KnowledgeSource]:
        return [s for s in self._sources.values() if s.trust_level is trust_level]

    def executable_sources(self) -> list[KnowledgeSource]:
        """Bo'lim 4 tekshiruvi uchun qulay yordamchi — `code_executable=True`
        bo'lgan yozuvlar HAR DOIM kam va aniq bo'lishi kutiladi."""
        return [s for s in self._sources.values() if s.code_executable]

    def search(self, keywords: list[str]) -> list[KnowledgeSource]:
        """`CapabilityRegistry.search()`/`public_apis` bilan bir xil
        oddiy pastki-satr-sanash naqshi — LLM chaqiruvisiz."""
        lowered = [k.strip().lower() for k in keywords if k.strip()]
        if not lowered:
            return []
        scored: list[tuple[int, KnowledgeSource]] = []
        for source in self._sources.values():
            blob = " ".join(
                [
                    source.name.lower(),
                    source.description.lower(),
                    source.category.value.lower(),
                    " ".join(source.capabilities).lower(),
                ]
            )
            score = sum(blob.count(kw) for kw in lowered)
            if score > 0:
                scored.append((score, source))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [source for _, source in scored]

    @property
    def count(self) -> int:
        return len(self._sources)


__all__ = ["SourceRegistry"]
