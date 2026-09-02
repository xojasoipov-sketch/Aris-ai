"""`github.search_repository`/`.analyze_repository`/`.compare_repositories`
tool testlari (JB-19) — `respx` bilan (HAQIQIY tarmoqqa chiqmasdan,
`test_telegram_tools.py`/`test_public_apis_adapters.py` bilan bir xil
naqsh).
"""

from __future__ import annotations

import base64

import httpx
import respx

from zet.domain.enums import PermissionLevel, RiskLevel, TrustLevel
from zet.tools.builtin.github import GitHubReadTool, GitHubWriteTool
from zet.tools.builtin.github_intel_tools import (
    GitHubAnalyzeRepositoryTool,
    GitHubCompareRepositoriesTool,
    GitHubSearchRepositoryTool,
)

_API = "https://api.github.com"


def _repo_json(
    full_name: str = "donnemartin/system-design-primer", **overrides: object
) -> dict[str, object]:
    base: dict[str, object] = {
        "name": full_name.split("/")[-1],
        "full_name": full_name,
        "description": "Learn how to design large-scale systems.",
        "language": "Python",
        "stargazers_count": 365000,
        "forks_count": 58000,
        "open_issues_count": 100,
        "license": {"spdx_id": "CC-BY-4.0"},
        "topics": ["system-design"],
        "default_branch": "master",
        "pushed_at": "2026-01-01T00:00:00Z",
        "archived": False,
        "html_url": f"https://github.com/{full_name}",
    }
    base |= overrides
    return base


# ── Tool identity — hech biri github.read/write bilan TO'QNASHMAYDI ──


class TestNoDuplicationWithOperationalGitHubTools:
    def test_names_do_not_collide(self) -> None:
        names = {
            GitHubSearchRepositoryTool().name,
            GitHubAnalyzeRepositoryTool().name,
            GitHubCompareRepositoriesTool().name,
            GitHubReadTool().name,
            GitHubWriteTool().name,
        }
        assert len(names) == 5

    def test_new_tools_are_read_only_low_risk(self) -> None:
        for tool in (
            GitHubSearchRepositoryTool(),
            GitHubAnalyzeRepositoryTool(),
            GitHubCompareRepositoriesTool(),
        ):
            assert tool.permission_level == PermissionLevel.READ
            assert tool.risk_level == RiskLevel.LOW
            assert tool.output_trust_level == TrustLevel.UNTRUSTED
            assert tool.idempotent is True


# ── github.search_repository ────────────────────────────────────────


class TestGitHubSearchRepositoryTool:
    @respx.mock
    async def test_successful_search_maps_results(self) -> None:
        respx.get(f"{_API}/search/repositories").mock(
            return_value=httpx.Response(
                200,
                json={
                    "total_count": 1,
                    "items": [_repo_json()],
                },
            )
        )
        tool = GitHubSearchRepositoryTool()
        result = await tool.execute({"query": "system design"})
        assert result.success is True
        assert result.output["total_count"] == 1
        assert result.output["results"][0]["repository"] == "donnemartin/system-design-primer"
        assert result.output["results"][0]["license"] == "CC-BY-4.0"

    @respx.mock
    async def test_language_and_min_stars_added_as_qualifiers(self) -> None:
        route = respx.get(f"{_API}/search/repositories").mock(
            return_value=httpx.Response(200, json={"total_count": 0, "items": []})
        )
        tool = GitHubSearchRepositoryTool()
        await tool.execute({"query": "agent", "language": "Python", "min_stars": 1000})
        sent_query = dict(route.calls.last.request.url.params)["q"]
        assert "agent" in sent_query
        assert "language:Python" in sent_query
        assert "stars:>=1000" in sent_query

    @respx.mock
    async def test_no_results_returns_empty_list_not_error(self) -> None:
        respx.get(f"{_API}/search/repositories").mock(
            return_value=httpx.Response(200, json={"total_count": 0, "items": []})
        )
        tool = GitHubSearchRepositoryTool()
        result = await tool.execute({"query": "totally-nonexistent-xyz-project"})
        assert result.success is True
        assert result.output["results"] == []

    @respx.mock
    async def test_rate_limited_maps_to_failed_result(self) -> None:
        respx.get(f"{_API}/search/repositories").mock(return_value=httpx.Response(403))
        tool = GitHubSearchRepositoryTool()
        result = await tool.execute({"query": "x"})
        assert result.success is False


# ── github.analyze_repository ───────────────────────────────────────


class TestGitHubAnalyzeRepositoryTool:
    @respx.mock
    async def test_successful_analysis(self) -> None:
        repo = "donnemartin/system-design-primer"
        respx.get(f"{_API}/repos/{repo}").mock(return_value=httpx.Response(200, json=_repo_json()))
        respx.get(f"{_API}/repos/{repo}/languages").mock(
            return_value=httpx.Response(200, json={"Python": 1000})
        )
        readme_b64 = base64.b64encode(b"# System Design Primer").decode()
        respx.get(f"{_API}/repos/{repo}/readme").mock(
            return_value=httpx.Response(200, json={"content": readme_b64, "encoding": "base64"})
        )
        respx.get(f"{_API}/repos/{repo}/contents/").mock(
            return_value=httpx.Response(200, json=[{"name": "README.md", "type": "file"}])
        )

        tool = GitHubAnalyzeRepositoryTool()
        result = await tool.execute({"repository": repo})
        assert result.success is True
        assert result.output["repository"] == repo
        assert result.output["license"] == "CC-BY-4.0"
        assert result.output["stars"] == 365000
        assert "System Design Primer" in result.output["readme_excerpt"]
        assert result.output["top_level_entries"] == ("README.md",)

    @respx.mock
    async def test_repo_not_found_returns_failed_result(self) -> None:
        respx.get(f"{_API}/repos/owner/nonexistent").mock(return_value=httpx.Response(404))
        tool = GitHubAnalyzeRepositoryTool()
        result = await tool.execute({"repository": "owner/nonexistent"})
        assert result.success is False
        assert "topilmadi" in (result.error or "")

    def test_invalid_repo_format_rejected(self) -> None:
        tool = GitHubAnalyzeRepositoryTool()
        import asyncio

        result = asyncio.run(tool.execute({"repository": "not-a-valid-repo-format"}))
        assert result.success is False


# ── github.compare_repositories ─────────────────────────────────────


class TestGitHubCompareRepositoriesTool:
    @respx.mock
    async def test_compares_multiple_repos(self) -> None:
        for repo in ("a/a", "b/b"):
            respx.get(f"{_API}/repos/{repo}").mock(
                return_value=httpx.Response(200, json=_repo_json(full_name=repo))
            )
            respx.get(f"{_API}/repos/{repo}/languages").mock(return_value=httpx.Response(404))
            respx.get(f"{_API}/repos/{repo}/readme").mock(return_value=httpx.Response(404))
            respx.get(f"{_API}/repos/{repo}/contents/").mock(return_value=httpx.Response(404))

        tool = GitHubCompareRepositoriesTool()
        result = await tool.execute({"repositories": ["a/a", "b/b"]})
        assert result.success is True
        assert result.output["compared"] == 2
        assert result.output["errors"] == {}

    @respx.mock
    async def test_one_missing_repo_does_not_fail_the_whole_comparison(self) -> None:
        respx.get(f"{_API}/repos/a/a").mock(
            return_value=httpx.Response(200, json=_repo_json(full_name="a/a"))
        )
        respx.get(f"{_API}/repos/a/a/languages").mock(return_value=httpx.Response(404))
        respx.get(f"{_API}/repos/a/a/readme").mock(return_value=httpx.Response(404))
        respx.get(f"{_API}/repos/a/a/contents/").mock(return_value=httpx.Response(404))
        respx.get(f"{_API}/repos/b/missing").mock(return_value=httpx.Response(404))

        tool = GitHubCompareRepositoriesTool()
        result = await tool.execute({"repositories": ["a/a", "b/missing"]})
        assert result.success is True  # tool o'zi muvaffaqiyatli — ichida qisman xato
        assert result.output["compared"] == 1
        assert result.output["requested"] == 2
        assert "b/missing" in result.output["errors"]

    async def test_too_few_repos_rejected(self) -> None:
        tool = GitHubCompareRepositoriesTool()
        result = await tool.execute({"repositories": ["a/a"]})
        assert result.success is False

    async def test_too_many_repos_rejected(self) -> None:
        tool = GitHubCompareRepositoriesTool()
        result = await tool.execute({"repositories": [f"o/{i}" for i in range(6)]})
        assert result.success is False
