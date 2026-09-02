"""GitHubReadTool/GitHubWriteTool — haqiqiy API rejimi (respx bilan, gap-analysis #13).

Stub rejim testlari `tests/test_developer.py`da — bu fayl faqat
`token`li (real) rejimni tekshiradi.
"""

from __future__ import annotations

import base64

import httpx
import respx

from zet.domain.tool import ToolResult
from zet.tools.builtin.github import GitHubReadTool, GitHubWriteTool

_TOKEN = "ghp_faketoken"
_BASE = "https://api.github.com"


def _assert_ok(result: ToolResult) -> None:
    assert result.success, result.error


class TestGitHubReadToolReal:
    def test_is_real_with_token(self) -> None:
        assert GitHubReadTool(token=_TOKEN).is_real is True

    def test_is_stub_without_token(self) -> None:
        assert GitHubReadTool().is_real is False

    @respx.mock
    async def test_get_issue_real(self) -> None:
        respx.get(f"{_BASE}/repos/owner/repo/issues/5").mock(
            return_value=httpx.Response(
                200,
                json={
                    "number": 5,
                    "title": "Real issue",
                    "body": "Real body",
                    "state": "open",
                    "labels": [{"name": "bug"}],
                },
            )
        )
        tool = GitHubReadTool(token=_TOKEN)
        result = await tool.execute({"action": "get_issue", "repo": "owner/repo", "number": 5})
        _assert_ok(result)
        assert result.output["title"] == "Real issue"
        assert result.output["labels"] == ["bug"]
        assert result.output["source"] == "github.read (api)"

    @respx.mock
    async def test_get_pr_real(self) -> None:
        respx.get(f"{_BASE}/repos/owner/repo/pulls/10").mock(
            return_value=httpx.Response(
                200,
                json={
                    "number": 10,
                    "title": "Real PR",
                    "body": "",
                    "state": "open",
                    "merged": False,
                },
            )
        )
        tool = GitHubReadTool(token=_TOKEN)
        result = await tool.execute({"action": "get_pr", "repo": "owner/repo", "number": 10})
        _assert_ok(result)
        assert result.output["title"] == "Real PR"

    @respx.mock
    async def test_list_issues_excludes_prs(self) -> None:
        respx.get(f"{_BASE}/repos/owner/repo/issues").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"number": 1, "title": "Issue", "state": "open"},
                    {
                        "number": 2,
                        "title": "A PR",
                        "state": "open",
                        "pull_request": {"url": "..."},
                    },
                ],
            )
        )
        tool = GitHubReadTool(token=_TOKEN)
        result = await tool.execute({"action": "list_issues", "repo": "owner/repo"})
        _assert_ok(result)
        assert result.output["total"] == 1
        assert result.output["issues"][0]["number"] == 1

    @respx.mock
    async def test_get_file_decodes_base64(self) -> None:
        content = base64.b64encode(b"# README\nHello").decode()
        respx.get(f"{_BASE}/repos/owner/repo/contents/README.md").mock(
            return_value=httpx.Response(200, json={"content": content})
        )
        tool = GitHubReadTool(token=_TOKEN)
        result = await tool.execute(
            {"action": "get_file", "repo": "owner/repo", "path": "README.md"}
        )
        _assert_ok(result)
        assert "Hello" in result.output["content"]

    @respx.mock
    async def test_404_returns_error(self) -> None:
        respx.get(f"{_BASE}/repos/owner/repo/issues/999").mock(return_value=httpx.Response(404))
        tool = GitHubReadTool(token=_TOKEN)
        result = await tool.execute({"action": "get_issue", "repo": "owner/repo", "number": 999})
        assert not result.success
        assert "topilmadi" in result.error.lower()

    @respx.mock
    async def test_403_returns_error(self) -> None:
        respx.get(f"{_BASE}/repos/owner/repo/issues/1").mock(return_value=httpx.Response(403))
        tool = GitHubReadTool(token=_TOKEN)
        result = await tool.execute({"action": "get_issue", "repo": "owner/repo", "number": 1})
        assert not result.success
        assert "403" in result.error

    @respx.mock
    async def test_timeout_returns_error(self) -> None:
        respx.get(f"{_BASE}/repos/owner/repo/issues/1").mock(
            side_effect=httpx.ConnectTimeout("timeout")
        )
        tool = GitHubReadTool(token=_TOKEN)
        result = await tool.execute({"action": "get_issue", "repo": "owner/repo", "number": 1})
        assert not result.success

    async def test_invalid_repo_still_validated_before_network(self) -> None:
        tool = GitHubReadTool(token=_TOKEN)
        result = await tool.execute({"action": "get_issue", "repo": "badformat"})
        assert not result.success
        assert "owner/name" in result.error

    async def test_aclose_own_client(self) -> None:
        tool = GitHubReadTool(token=_TOKEN)
        tool._get_client()
        await tool.aclose()

    async def test_aclose_external_client_not_closed(self) -> None:
        client = httpx.AsyncClient()
        tool = GitHubReadTool(token=_TOKEN, client=client)
        await tool.aclose()
        assert client.is_closed is False
        await client.aclose()


class TestGitHubWriteToolReal:
    @respx.mock
    async def test_create_pr_real(self) -> None:
        respx.post(f"{_BASE}/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(
                201,
                json={
                    "number": 7,
                    "title": "Fix bug",
                    "html_url": "https://github.com/owner/repo/pull/7",
                },
            )
        )
        tool = GitHubWriteTool(token=_TOKEN)
        result = await tool.execute(
            {"action": "create_pr", "repo": "owner/repo", "title": "Fix bug", "branch": "fix"}
        )
        _assert_ok(result)
        assert result.output["number"] == 7
        assert result.output["url"].endswith("/pull/7")

    @respx.mock
    async def test_create_pr_without_branch_fails(self) -> None:
        tool = GitHubWriteTool(token=_TOKEN)
        result = await tool.execute({"action": "create_pr", "repo": "owner/repo", "title": "x"})
        assert not result.success

    @respx.mock
    async def test_add_comment_real(self) -> None:
        respx.post(f"{_BASE}/repos/owner/repo/issues/5/comments").mock(
            return_value=httpx.Response(201, json={"id": 999})
        )
        tool = GitHubWriteTool(token=_TOKEN)
        result = await tool.execute(
            {"action": "add_comment", "repo": "owner/repo", "number": 5, "body": "Fixed"}
        )
        _assert_ok(result)
        assert result.output["comment_id"] == 999

    @respx.mock
    async def test_create_issue_real(self) -> None:
        respx.post(f"{_BASE}/repos/owner/repo/issues").mock(
            return_value=httpx.Response(
                201,
                json={
                    "number": 55,
                    "title": "New bug",
                    "html_url": "https://github.com/owner/repo/issues/55",
                },
            )
        )
        tool = GitHubWriteTool(token=_TOKEN)
        result = await tool.execute(
            {"action": "create_issue", "repo": "owner/repo", "title": "New bug"}
        )
        _assert_ok(result)
        assert result.output["number"] == 55
