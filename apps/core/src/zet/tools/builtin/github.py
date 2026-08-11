"""GitHub toollar — issue/PR boshqaruvi (Bo'lim 7).

`token` berilsa — haqiqiy GitHub REST API (`api.github.com`)ga chiqadi.
`token` berilmasa (default) — stub rejim: hech qanday tarmoq chaqiruvi
yo'q, sinov uchun barqaror soxta javoblar.

Ilgari bu klass HAR DOIM stub edi — `token` parametri umuman yo'q edi
(gap-analysis #13: "every `_execute()` branch is a hardcoded stub").

Xavfsizlik:
    - github.read: READ ruxsat, UNTRUSTED output (issue/PR matni tashqi
      foydalanuvchilar yozgan — A-05)
    - github.write: WRITE ruxsat, SYSTEM trust (PR/comment yaratish)
    - Token hech qachon log qilinmaydi

Bog'liq qarorlar:
    Bo'lim 7 — Developer/GitHub
    A-05 — tashqi matn UNTRUSTED
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
import structlog

from zet.domain.enums import PermissionLevel, TrustLevel
from zet.tools.base import Tool, ToolError

log = structlog.get_logger(__name__)

_API_BASE = "https://api.github.com"


def _validate_repo(repo: str) -> None:
    if "/" not in repo or repo.startswith("/") or repo.endswith("/") or repo.count("/") != 1:
        raise ToolError(f"Repo formati noto'g'ri: '{repo}'. 'owner/name' kerak.")


class _GitHubHttpMixin:
    """`GitHubReadTool`/`GitHubWriteTool` uchun umumiy HTTP klient boshqaruvi."""

    _token: str | None
    _client: httpx.AsyncClient | None
    _owns_client: bool

    def _init_http(self, *, token: str | None, client: httpx.AsyncClient | None) -> None:
        self._token = token
        self._client = client
        self._owns_client = client is None

    @property
    def is_real(self) -> bool:
        """Haqiqiy API ishlatilyaptimi (token bor)."""
        return bool(self._token)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=_API_BASE,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        return self._client

    async def aclose(self) -> None:
        """HTTP klientni yopish (agar biz yaratgan bo'lsak)."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self._get_client().request(method, path, timeout=30.0, **kwargs)
        except httpx.TimeoutException as exc:
            raise ToolError(f"GitHub API timeout: {path}") from exc
        except httpx.HTTPError as exc:
            raise ToolError(f"GitHub API xatosi: {exc}") from exc

        if response.status_code == 404:
            raise ToolError(f"GitHub'da topilmadi: {path}")
        if response.status_code == 403:
            raise ToolError("GitHub API ruxsat rad etildi (403) — token tekshiring/rate limit")
        if response.status_code >= 400:
            raise ToolError(f"GitHub API xato ({response.status_code}): {response.text[:300]}")

        if response.status_code == 204:
            return {}
        return response.json()


class GitHubReadTool(_GitHubHttpMixin, Tool):
    """GitHub dan o'qish — issue, PR, fayl ko'rish.

    Output UNTRUSTED: issue/PR matni tashqi foydalanuvchilar yozgan.
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._init_http(token=token, client=client)

    @property
    def name(self) -> str:
        return "github.read"

    @property
    def description(self) -> str:
        return "GitHub repo/issue/PR o'qish — natija UNTRUSTED"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Amal turi",
                    "enum": ["get_issue", "get_pr", "list_issues", "get_file"],
                },
                "repo": {
                    "type": "string",
                    "description": "Repo (owner/name formatida)",
                },
                "number": {
                    "type": "integer",
                    "description": "Issue yoki PR raqami",
                },
                "path": {
                    "type": "string",
                    "description": "Fayl yo'li (get_file uchun)",
                },
            },
            "required": ["action", "repo"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    @property
    def output_trust_level(self) -> TrustLevel:
        return TrustLevel.UNTRUSTED

    @property
    def idempotent(self) -> bool:
        return True

    @property
    def timeout_s(self) -> int:
        return 30

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        action = params["action"]
        repo = params["repo"]
        _validate_repo(repo)

        if not self.is_real:
            return self._stub(action, repo, params)

        if action == "get_issue":
            return await self._real_get_issue(repo, params.get("number", 1))
        if action == "get_pr":
            return await self._real_get_pr(repo, params.get("number", 1))
        if action == "list_issues":
            return await self._real_list_issues(repo)
        if action == "get_file":
            return await self._real_get_file(repo, params.get("path", ""))

        raise ToolError(f"Noma'lum amal: '{action}'")

    def _stub(self, action: str, repo: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "get_issue":
            return self._stub_get_issue(repo, params.get("number", 1))
        if action == "get_pr":
            return self._stub_get_pr(repo, params.get("number", 1))
        if action == "list_issues":
            return self._stub_list_issues(repo)
        if action == "get_file":
            return self._stub_get_file(repo, params.get("path", ""))
        raise ToolError(f"Noma'lum amal: '{action}'")

    # ── Real API ──────────────────────────────────────────────────

    async def _real_get_issue(self, repo: str, number: int) -> dict[str, Any]:
        data = await self._request("GET", f"/repos/{repo}/issues/{number}")
        return {
            "action": "get_issue",
            "repo": repo,
            "number": data.get("number", number),
            "title": data.get("title", ""),
            "body": data.get("body") or "",
            "state": data.get("state", "unknown"),
            "labels": [label.get("name", "") for label in data.get("labels", [])],
            "source": "github.read (api)",
        }

    async def _real_get_pr(self, repo: str, number: int) -> dict[str, Any]:
        data = await self._request("GET", f"/repos/{repo}/pulls/{number}")
        return {
            "action": "get_pr",
            "repo": repo,
            "number": data.get("number", number),
            "title": data.get("title", ""),
            "body": data.get("body") or "",
            "state": data.get("state", "unknown"),
            "merged": bool(data.get("merged", False)),
            "source": "github.read (api)",
        }

    async def _real_list_issues(self, repo: str) -> dict[str, Any]:
        data = await self._request("GET", f"/repos/{repo}/issues", params={"per_page": 30})
        issues = [
            {
                "number": item.get("number"),
                "title": item.get("title", ""),
                "state": item.get("state"),
            }
            for item in data
            if "pull_request" not in item  # PR'lar ham /issues'da chiqadi — chiqarib tashlash
        ]
        return {
            "action": "list_issues",
            "repo": repo,
            "issues": issues,
            "total": len(issues),
            "source": "github.read (api)",
        }

    async def _real_get_file(self, repo: str, path: str) -> dict[str, Any]:
        if not path:
            raise ToolError("Fayl yo'li ko'rsatilmadi")
        data = await self._request("GET", f"/repos/{repo}/contents/{path}")
        content_b64 = data.get("content", "")
        try:
            content = base64.b64decode(content_b64).decode("utf-8", errors="replace")
        except (ValueError, TypeError) as exc:
            raise ToolError(f"Fayl kontentini dekodlab bo'lmadi: {exc}") from exc
        return {
            "action": "get_file",
            "repo": repo,
            "path": path,
            "content": content,
            "source": "github.read (api)",
        }

    # ── Stub ──────────────────────────────────────────────────────

    def _stub_get_issue(self, repo: str, number: int) -> dict[str, Any]:
        return {
            "action": "get_issue",
            "repo": repo,
            "number": number,
            "title": f"Issue #{number} (stub)",
            "body": f"Issue #{number} matni — stub. Token berilsa haqiqiy API ishlaydi.",
            "state": "open",
            "labels": ["bug"],
            "source": "github.read (stub)",
        }

    def _stub_get_pr(self, repo: str, number: int) -> dict[str, Any]:
        return {
            "action": "get_pr",
            "repo": repo,
            "number": number,
            "title": f"PR #{number} (stub)",
            "body": f"PR #{number} tavsifi — stub.",
            "state": "open",
            "merged": False,
            "source": "github.read (stub)",
        }

    def _stub_list_issues(self, repo: str) -> dict[str, Any]:
        return {
            "action": "list_issues",
            "repo": repo,
            "issues": [
                {"number": 1, "title": "Issue #1 (stub)", "state": "open"},
                {"number": 2, "title": "Issue #2 (stub)", "state": "closed"},
            ],
            "total": 2,
            "source": "github.read (stub)",
        }

    def _stub_get_file(self, repo: str, path: str) -> dict[str, Any]:
        if not path:
            raise ToolError("Fayl yo'li ko'rsatilmadi")
        return {
            "action": "get_file",
            "repo": repo,
            "path": path,
            "content": f"# {path} (stub)\nFayl kontenti — stub.",
            "source": "github.read (stub)",
        }


class GitHubWriteTool(_GitHubHttpMixin, Tool):
    """GitHub ga yozish — PR ochish, comment qo'shish.

    WRITE ruxsat kerak. Output SYSTEM (biz yozamiz).
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._init_http(token=token, client=client)

    @property
    def name(self) -> str:
        return "github.write"

    @property
    def description(self) -> str:
        return "GitHub PR/comment yaratish (WRITE ruxsat kerak)"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Amal turi",
                    "enum": ["create_pr", "add_comment", "create_issue"],
                },
                "repo": {
                    "type": "string",
                    "description": "Repo (owner/name formatida)",
                },
                "title": {
                    "type": "string",
                    "description": "PR/issue sarlavhasi",
                },
                "body": {
                    "type": "string",
                    "description": "PR/issue/comment matni",
                },
                "number": {
                    "type": "integer",
                    "description": "Issue/PR raqami (comment uchun)",
                },
                "branch": {
                    "type": "string",
                    "description": "PR bosh branch",
                },
                "base": {
                    "type": "string",
                    "description": "PR asosiy branch (default: main)",
                    "default": "main",
                },
            },
            "required": ["action", "repo"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.WRITE

    @property
    def output_trust_level(self) -> TrustLevel:
        return TrustLevel.SYSTEM

    @property
    def idempotent(self) -> bool:
        return False

    @property
    def timeout_s(self) -> int:
        return 30

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        action = params["action"]
        repo = params["repo"]
        _validate_repo(repo)

        if not self.is_real:
            return self._stub(action, repo, params)

        if action == "create_pr":
            return await self._real_create_pr(repo, params)
        if action == "add_comment":
            return await self._real_add_comment(repo, params)
        if action == "create_issue":
            return await self._real_create_issue(repo, params)

        raise ToolError(f"Noma'lum amal: '{action}'")

    def _stub(self, action: str, repo: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "create_pr":
            return self._stub_create_pr(repo, params)
        if action == "add_comment":
            return self._stub_add_comment(repo, params)
        if action == "create_issue":
            return self._stub_create_issue(repo, params)
        raise ToolError(f"Noma'lum amal: '{action}'")

    # ── Real API ──────────────────────────────────────────────────

    async def _real_create_pr(self, repo: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "title": params.get("title", "Untitled PR"),
            "head": params.get("branch", ""),
            "base": params.get("base", "main"),
            "body": params.get("body", ""),
        }
        if not payload["head"]:
            raise ToolError("PR yaratish uchun 'branch' kerak")
        data = await self._request("POST", f"/repos/{repo}/pulls", json=payload)
        return {
            "action": "create_pr",
            "repo": repo,
            "number": data.get("number"),
            "title": data.get("title"),
            "branch": payload["head"],
            "base": payload["base"],
            "url": data.get("html_url", ""),
            "source": "github.write (api)",
        }

    async def _real_add_comment(self, repo: str, params: dict[str, Any]) -> dict[str, Any]:
        number = params.get("number")
        if number is None:
            raise ToolError("Comment uchun issue/PR raqami kerak")
        payload = {"body": params.get("body", "")}
        data = await self._request("POST", f"/repos/{repo}/issues/{number}/comments", json=payload)
        return {
            "action": "add_comment",
            "repo": repo,
            "number": number,
            "comment_id": data.get("id"),
            "source": "github.write (api)",
        }

    async def _real_create_issue(self, repo: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "title": params.get("title", "Untitled Issue"),
            "body": params.get("body", ""),
        }
        data = await self._request("POST", f"/repos/{repo}/issues", json=payload)
        return {
            "action": "create_issue",
            "repo": repo,
            "number": data.get("number"),
            "title": data.get("title"),
            "url": data.get("html_url", ""),
            "source": "github.write (api)",
        }

    # ── Stub ──────────────────────────────────────────────────────

    def _stub_create_pr(self, repo: str, params: dict[str, Any]) -> dict[str, Any]:
        title = params.get("title", "Untitled PR")
        branch = params.get("branch", "feature")
        base = params.get("base", "main")
        return {
            "action": "create_pr",
            "repo": repo,
            "number": 42,
            "title": title,
            "branch": branch,
            "base": base,
            "url": f"https://github.com/{repo}/pull/42",
            "source": "github.write (stub)",
        }

    def _stub_add_comment(self, repo: str, params: dict[str, Any]) -> dict[str, Any]:
        number = params.get("number")
        if number is None:
            raise ToolError("Comment uchun issue/PR raqami kerak")
        return {
            "action": "add_comment",
            "repo": repo,
            "number": number,
            "comment_id": 12345,
            "source": "github.write (stub)",
        }

    def _stub_create_issue(self, repo: str, params: dict[str, Any]) -> dict[str, Any]:
        title = params.get("title", "Untitled Issue")
        return {
            "action": "create_issue",
            "repo": repo,
            "number": 99,
            "title": title,
            "url": f"https://github.com/{repo}/issues/99",
            "source": "github.write (stub)",
        }
