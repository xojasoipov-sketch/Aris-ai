"""GitHub toollar — issue/PR boshqaruvi (Bo'lim 7).

Stub implementatsiya — produksiyada GitHub API bilan almashtiriladi.
Developer Agent ushbu toollardan foydalanadi.

Xavfsizlik:
    - github.read: READ ruxsat, UNTRUSTED output (issue/PR matni)
    - github.write: WRITE ruxsat, SYSTEM trust (PR/comment yaratish)

Bog'liq qarorlar:
    Bo'lim 7 — Developer/GitHub
    A-05 — tashqi matn UNTRUSTED
"""

from __future__ import annotations

from typing import Any

import structlog

from zet.domain.enums import PermissionLevel, TrustLevel
from zet.tools.base import Tool, ToolError

log = structlog.get_logger(__name__)


class GitHubReadTool(Tool):
    """GitHub dan o'qish — issue, PR, fayl ko'rish.

    Output UNTRUSTED: issue/PR matni tashqi foydalanuvchilar yozgan.
    """

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

        if "/" not in repo:
            raise ToolError(f"Repo formatii noto'g'ri: '{repo}'. 'owner/name' kerak.")

        if action == "get_issue":
            return self._stub_get_issue(repo, params.get("number", 1))
        if action == "get_pr":
            return self._stub_get_pr(repo, params.get("number", 1))
        if action == "list_issues":
            return self._stub_list_issues(repo)
        if action == "get_file":
            return self._stub_get_file(repo, params.get("path", ""))

        raise ToolError(f"Noma'lum amal: '{action}'")

    def _stub_get_issue(self, repo: str, number: int) -> dict[str, Any]:
        return {
            "action": "get_issue",
            "repo": repo,
            "number": number,
            "title": f"Issue #{number} (stub)",
            "body": f"Issue #{number} matni — stub. Haqiqiy API Bo'lim 7 produksiyada.",
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


class GitHubWriteTool(Tool):
    """GitHub ga yozish — PR ochish, comment qo'shish.

    WRITE ruxsat kerak. Output SYSTEM (biz yozamiz).
    Stub: haqiqiy API chaqirmaydi.
    """

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

        if "/" not in repo:
            raise ToolError(f"Repo formati noto'g'ri: '{repo}'. 'owner/name' kerak.")

        if action == "create_pr":
            return self._stub_create_pr(repo, params)
        if action == "add_comment":
            return self._stub_add_comment(repo, params)
        if action == "create_issue":
            return self._stub_create_issue(repo, params)

        raise ToolError(f"Noma'lum amal: '{action}'")

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
