"""`analyze_repository()` testlari (JB-19, spec Bo'lim 5/11) — soxta
`request` callable bilan (haqiqiy HTTP yo'q), bazaviy mantiqni izolyatsiya
qilib sinash uchun (`test_github_intel_tools.py` esa `respx` bilan
TO'LIQ HTTP qatlamini sinaydi).

MUHIM: bu funksiya "design pattern" yoki "duplicate functionality"
degan XULOSA chiqarmaydi — faqat FAKT. Testlar buni tasdiqlaydi: chiqish
faqat GitHub javobidan olingan qiymatlar, hech qanday qo'shimcha
"tushuncha" yo'q.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

from zet.integrations.github_intel.analyzer.repository_analyzer import analyze_repository
from zet.tools.base import ToolError


def _readme_response(text: str) -> dict[str, Any]:
    return {"content": base64.b64encode(text.encode("utf-8")).decode("ascii"), "encoding": "base64"}


def _meta_response(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "system-design-primer",
        "description": "Learn how to design large-scale systems.",
        "language": "Python",
        "stargazers_count": 365000,
        "forks_count": 58000,
        "open_issues_count": 100,
        "license": {"spdx_id": "CC-BY-4.0"},
        "topics": ["system-design", "interview"],
        "default_branch": "master",
        "pushed_at": "2026-01-01T00:00:00Z",
        "archived": False,
        "html_url": "https://github.com/donnemartin/system-design-primer",
    }
    base |= overrides
    return base


class _FakeRequester:
    """`RequestFn` imzosiga mos — yo'l bo'yicha oldindan tayyorlangan
    javob (yoki istisno) qaytaradi."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    async def __call__(self, method: str, path: str, **kwargs: Any) -> Any:
        self.calls.append(path)
        result = self._responses.get(path)
        if isinstance(result, Exception):
            raise result
        if result is None:
            raise ToolError(f"soxta 404: {path}")
        return result


class TestAnalyzeRepositoryHappyPath:
    async def test_full_response_maps_every_field(self) -> None:
        requester = _FakeRequester(
            {
                "/repos/donnemartin/system-design-primer": _meta_response(),
                "/repos/donnemartin/system-design-primer/languages": {"Python": 12345, "Shell": 100},
                "/repos/donnemartin/system-design-primer/readme": _readme_response(
                    "# System Design Primer\n\nLearn to design systems."
                ),
                "/repos/donnemartin/system-design-primer/contents/": [
                    {"name": "README.md", "type": "file"},
                    {"name": "solutions", "type": "dir"},
                ],
            }
        )
        analysis = await analyze_repository(requester, "donnemartin/system-design-primer")

        assert analysis.repository == "donnemartin/system-design-primer"
        assert analysis.name == "system-design-primer"
        assert analysis.primary_language == "Python"
        assert analysis.languages == {"Python": 12345, "Shell": 100}
        assert analysis.license == "CC-BY-4.0"
        assert analysis.stars == 365000
        assert analysis.forks == 58000
        assert analysis.topics == ("system-design", "interview")
        assert analysis.default_branch == "master"
        assert analysis.archived is False
        assert "System Design Primer" in (analysis.readme_excerpt or "")
        assert analysis.top_level_entries == ("README.md", "solutions")

    async def test_readme_truncated_flag_set_when_long(self) -> None:
        long_text = "x" * 5000
        requester = _FakeRequester(
            {
                "/repos/o/r": _meta_response(),
                "/repos/o/r/readme": _readme_response(long_text),
            }
        )
        analysis = await analyze_repository(requester, "o/r")
        assert analysis.readme_truncated is True
        assert len(analysis.readme_excerpt or "") == 2000

    async def test_short_readme_not_truncated(self) -> None:
        requester = _FakeRequester(
            {
                "/repos/o/r": _meta_response(),
                "/repos/o/r/readme": _readme_response("short"),
            }
        )
        analysis = await analyze_repository(requester, "o/r")
        assert analysis.readme_truncated is False
        assert analysis.readme_excerpt == "short"


class TestAnalyzeRepositoryGracefulDegradation:
    """Bo'lim: ikkilamchi chaqiruvlar ENG YAXSHI-HARAKAT — biri
    muvaffaqiyatsiz bo'lsa, BUTUN tahlil yiqilmaydi."""

    async def test_missing_languages_endpoint_does_not_crash(self) -> None:
        requester = _FakeRequester({"/repos/o/r": _meta_response()})
        analysis = await analyze_repository(requester, "o/r")
        assert analysis.languages == {}
        assert analysis.name == "system-design-primer"  # asosiy ma'lumot baribir bor

    async def test_missing_readme_does_not_crash(self) -> None:
        requester = _FakeRequester({"/repos/o/r": _meta_response()})
        analysis = await analyze_repository(requester, "o/r")
        assert analysis.readme_excerpt is None
        assert analysis.readme_truncated is False

    async def test_missing_contents_does_not_crash(self) -> None:
        requester = _FakeRequester({"/repos/o/r": _meta_response()})
        analysis = await analyze_repository(requester, "o/r")
        assert analysis.top_level_entries == ()

    async def test_malformed_readme_base64_does_not_crash(self) -> None:
        requester = _FakeRequester(
            {
                "/repos/o/r": _meta_response(),
                "/repos/o/r/readme": {"content": "not-valid-base64!!!", "encoding": "base64"},
            }
        )
        analysis = await analyze_repository(requester, "o/r")
        # Yiqilmaydi — yo muvaffaqiyatli dekodlanadi (base64 ba'zan
        # noto'g'ri paddingni ham qabul qiladi), yo None qoladi.
        assert analysis.name == "system-design-primer"

    async def test_primary_request_failure_propagates(self) -> None:
        """Asosiy chaqiruv (repo metadata) muvaffaqiyatsiz bo'lsa —
        TAHLIL UMUMAN mumkin emas, bu YIQILISHI kerak (ikkilamchilardan farqli)."""
        requester = _FakeRequester({})  # /repos/o/r ham yo'q
        with pytest.raises(ToolError):
            await analyze_repository(requester, "o/r")


class TestAnalyzeRepositoryNoFabrication:
    """Bo'lim 11: hech qanday qiymat TAXMIN QILINMAYDI — faqat GitHub
    HAQIQATAN qaytargan narsa."""

    async def test_noassertion_license_becomes_none_not_fabricated(self) -> None:
        """GitHub litsenziyani aniqlay olmasa 'NOASSERTION' qaytaradi —
        bu 'litsenziyasiz' DEGANI EMAS, 'GitHub aniqlay olmadi' degani.
        Shuning uchun `None` (noma'lum), soxta qiymat emas."""
        requester = _FakeRequester(
            {"/repos/o/r": _meta_response(license={"spdx_id": "NOASSERTION"})}
        )
        analysis = await analyze_repository(requester, "o/r")
        assert analysis.license is None

    async def test_no_license_field_at_all_becomes_none(self) -> None:
        requester = _FakeRequester({"/repos/o/r": _meta_response(license=None)})
        analysis = await analyze_repository(requester, "o/r")
        assert analysis.license is None

    async def test_missing_description_stays_none(self) -> None:
        requester = _FakeRequester({"/repos/o/r": _meta_response(description=None)})
        analysis = await analyze_repository(requester, "o/r")
        assert analysis.description is None

    async def test_zero_stars_stays_zero_not_omitted(self) -> None:
        requester = _FakeRequester({"/repos/o/r": _meta_response(stargazers_count=0)})
        analysis = await analyze_repository(requester, "o/r")
        assert analysis.stars == 0
