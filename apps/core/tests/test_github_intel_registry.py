"""GitHub Intelligence — Source Registry testlari (JB-19, spec Bo'lim 2/3/4).

Eng muhim tekshiruv: `code_executable=False` DEFAULT (Bo'lim 4 qat'iy
qoidasi) va faqat public-apis'ning HAQIQIY (`integrations/public_apis/`)
integratsiyasi `True`ga ega — qolgan 8 tasi HECH QACHON ijro etilmaydi.
"""

from __future__ import annotations

from zet.integrations.github_intel.registry.models import (
    IntegrationAction,
    KnowledgeSource,
    SourceCategory,
    SourceType,
    TrustLevel,
    source_id,
)
from zet.integrations.github_intel.registry.repository import SourceRegistry
from zet.integrations.github_intel.registry.seed import builtin_sources


def _source(repository: str = "owner/repo", **overrides: object) -> KnowledgeSource:
    base: dict[str, object] = {
        "id": source_id(repository),
        "repository": repository,
        "name": "Test",
        "description": "test source",
        "category": SourceCategory.ENGINEERING_REFERENCE,
        "license": "MIT",
        "source_type": SourceType.GITHUB_REPOSITORY,
        "trust_level": TrustLevel.EXTERNAL_SOURCE,
        "capabilities": ("test",),
        "documentation_url": f"https://github.com/{repository}",
    }
    base |= overrides
    return KnowledgeSource(**base)  # type: ignore[arg-type]


# ── models.py ────────────────────────────────────────────────────────


class TestSourceId:
    def test_deterministic(self) -> None:
        assert source_id("owner/repo") == source_id("owner/repo")

    def test_case_and_whitespace_insensitive(self) -> None:
        assert source_id("  Owner/Repo  ") == source_id("owner/repo")

    def test_different_repos_differ(self) -> None:
        assert source_id("owner/repo") != source_id("owner/other")


class TestKnowledgeSourceDefaults:
    def test_code_executable_defaults_false(self) -> None:
        """QAT'IY QOIDA (Bo'lim 4): repo kodi DEFAULT holatda ISHGA
        TUSHIRILMAYDI — buni HAR safar qo'lda True qilish kerak."""
        source = _source()
        assert source.code_executable is False

    def test_enabled_defaults_true(self) -> None:
        assert _source().enabled is True

    def test_integration_action_defaults_none(self) -> None:
        assert _source().integration_action is None

    def test_is_frozen(self) -> None:
        source = _source()
        try:
            source.trust_level = TrustLevel.TRUSTED_REFERENCE  # type: ignore[misc]
        except AttributeError:
            pass
        else:
            raise AssertionError("KnowledgeSource frozen bo'lishi kerak edi")


# ── seed.py — spec'ning 9 ta repo'si ────────────────────────────────


class TestBuiltinSources:
    def test_ships_exactly_nine(self) -> None:
        """Spec ANIQ 9 ta repo so'ragan — ko'proq ham, kamroq ham emas."""
        assert len(builtin_sources()) == 9

    def test_all_repositories_are_unique(self) -> None:
        sources = builtin_sources()
        repos = [s.repository for s in sources]
        assert len(repos) == len(set(repos))

    def test_all_ids_are_unique(self) -> None:
        sources = builtin_sources()
        ids = [s.id for s in sources]
        assert len(ids) == len(set(ids))

    def test_only_public_apis_is_code_executable(self) -> None:
        """ENG MUHIM xavfsizlik invarianti: 9 tadan FAQAT bittasi
        (public-apis, chunki `integrations/public_apis/` HAQIQIY qurilgan)
        `code_executable=True`ga ega bo'lishi kerak."""
        executable = [s.repository for s in builtin_sources() if s.code_executable]
        assert executable == ["public-apis/public-apis"]

    def test_every_source_has_a_non_placeholder_license_or_is_flagged(self) -> None:
        """Litsenziya maydoni bo'sh QOLDIRILMAYDI — yo haqiqiy SPDX, yo
        ANIQ 'PENDING_VERIFICATION' belgisi (soxta/taxminiy qiymat emas)."""
        for source in builtin_sources():
            assert source.license, f"{source.repository}: litsenziya bo'sh"

    def test_every_source_has_notes_explaining_the_decision(self) -> None:
        """Halollik: har bir trust/action qarori ASOSSIZ ko'rinmasin."""
        for source in builtin_sources():
            assert source.notes.strip(), f"{source.repository}: notes bo'sh"

    def test_openclaw_deeply_audited_and_categorized(self) -> None:
        openclaw = next(s for s in builtin_sources() if s.repository == "openclaw/openclaw")
        assert openclaw.category is SourceCategory.AI_AGENT
        assert openclaw.trust_level is TrustLevel.VERIFIED_SOURCE
        assert openclaw.license == "MIT"

    def test_system_design_primer_is_verified_not_just_external(self) -> None:
        """Bo'lim 3: system-design-primer chuqur audit qilingan (kod emas,
        lekin ARXITEKTURA qarorlariga ta'sir qiladi) — shuning uchun
        VERIFIED_SOURCE, oddiy EXTERNAL_SOURCE emas."""
        sdp = next(
            s for s in builtin_sources() if s.repository == "donnemartin/system-design-primer"
        )
        assert sdp.trust_level is TrustLevel.VERIFIED_SOURCE

    def test_developer_roadmap_license_restriction_is_recorded(self) -> None:
        """Jonli tekshirilgan haqiqiy topilma: NC-ND litsenziya — mazmun
        ko'chirish TAQIQLANGAN. Bu notes'da AYNAN qayd etilishi kerak,
        aks holda kelajakda kimdir mazmunni ko'chirib qo'yishi mumkin."""
        roadmap = next(
            s for s in builtin_sources() if s.repository == "nilbuild/developer-roadmap"
        )
        assert "NC" in roadmap.license or "ND" in roadmap.license
        assert roadmap.trust_level is TrustLevel.EXTERNAL_SOURCE
        assert roadmap.integration_action is IntegrationAction.REFERENCE_ONLY


# ── repository.py ────────────────────────────────────────────────────


class TestSourceRegistry:
    def test_register_and_get(self) -> None:
        reg = SourceRegistry()
        source = _source()
        reg.register(source)
        assert reg.get(source.id) is source
        assert reg.count == 1

    def test_get_by_repository_case_insensitive(self) -> None:
        reg = SourceRegistry()
        source = _source("Owner/Repo")
        reg.register(source)
        assert reg.get_by_repository("owner/repo") is source

    def test_unknown_id_returns_none(self) -> None:
        assert SourceRegistry().get("nonexistent") is None

    def test_register_many_and_all(self) -> None:
        reg = SourceRegistry()
        reg.register_many(builtin_sources())
        assert reg.count == 9
        assert len(reg.all()) == 9

    def test_by_category(self) -> None:
        reg = SourceRegistry()
        reg.register_many(builtin_sources())
        system_design = reg.by_category(SourceCategory.SYSTEM_DESIGN)
        assert [s.repository for s in system_design] == ["donnemartin/system-design-primer"]

    def test_by_trust_level(self) -> None:
        reg = SourceRegistry()
        reg.register_many(builtin_sources())
        trusted = reg.by_trust_level(TrustLevel.TRUSTED_REFERENCE)
        assert [s.repository for s in trusted] == ["public-apis/public-apis"]

    def test_executable_sources_matches_code_executable_flag(self) -> None:
        reg = SourceRegistry()
        reg.register_many(builtin_sources())
        assert [s.repository for s in reg.executable_sources()] == ["public-apis/public-apis"]

    def test_search_by_keyword(self) -> None:
        reg = SourceRegistry()
        reg.register_many(builtin_sources())
        hits = reg.search(["agent"])
        assert any(s.repository == "openclaw/openclaw" for s in hits)

    def test_search_empty_keywords_returns_empty(self) -> None:
        reg = SourceRegistry()
        reg.register_many(builtin_sources())
        assert reg.search([]) == []
        assert reg.search(["   "]) == []

    def test_search_no_match_returns_empty(self) -> None:
        reg = SourceRegistry()
        reg.register_many(builtin_sources())
        assert reg.search(["totally-unrelated-keyword-xyz"]) == []

    def test_search_sorted_by_score_descending(self) -> None:
        reg = SourceRegistry()
        reg.register(_source("a/a", description="python python python", capabilities=()))
        reg.register(_source("b/b", description="python", capabilities=()))
        hits = reg.search(["python"])
        assert hits[0].repository == "a/a"
