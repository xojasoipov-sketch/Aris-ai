"""Web Reader tool — veb sahifa o'qish (Bo'lim 7).

Veb sahifalarni yuklab, matnini ajratib chiqaradi.
Natija har doim UNTRUSTED (A-05).

Xavfsizlik:
    - output trust_level = UNTRUSTED
    - permission = READ
    - idempotent = True
    - URL validatsiyasi: faqat http/https
    - Hajm chegarasi: max 500KB
    - Timeout: 15s

Bog'liq qarorlar:
    A-05 — untrusted chegara
    Bo'lim 7 — internet toollar
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import structlog

from zet.domain.enums import PermissionLevel, TrustLevel
from zet.tools.base import Tool, ToolError

log = structlog.get_logger(__name__)

# URL xavfsizligi
_ALLOWED_SCHEMES = frozenset({"http", "https"})
_MAX_CONTENT_BYTES = 500_000  # 500 KB
_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",  # noqa: S104
        "::1",
        "169.254.169.254",  # AWS metadata
        "metadata.google.internal",  # GCP metadata
    }
)


def _validate_url(url: str) -> str:
    """URL ni validatsiya qilish — faqat xavfsiz URL lar ruxsat etiladi.

    Raises:
        ToolError: URL xavfsiz emas
    """
    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise ToolError(f"URL tahlil qilib bo'lmadi: {exc}") from exc

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ToolError(f"Faqat http/https ruxsat etiladi, '{parsed.scheme}' emas")

    if not parsed.hostname:
        raise ToolError("URL da host topilmadi")

    hostname = parsed.hostname.lower()
    if hostname in _BLOCKED_HOSTS:
        raise ToolError(f"Bloklangan host: '{hostname}' (ichki tarmoq)")

    # Ichki IP diapazonlarini tekshirish
    if _is_private_ip(hostname):
        raise ToolError(f"Ichki IP manzilga ulanish taqiqlangan: '{hostname}'")

    return url


def _is_private_ip(hostname: str) -> bool:
    """Ichki IP manzilni aniqlash (SSRF oldini olish)."""
    # Oddiy IP formatini tekshirish
    parts = hostname.split(".")
    if len(parts) != 4:
        return False
    try:
        octets = [int(p) for p in parts]
    except ValueError:
        return False

    if not all(0 <= o <= 255 for o in octets):
        return False

    # RFC 1918 diapazonlari
    if octets[0] == 10:
        return True
    if octets[0] == 172 and 16 <= octets[1] <= 31:
        return True
    return octets[0] == 192 and octets[1] == 168


def _extract_text(html: str) -> str:
    """HTML dan sodda matn ajratish (kutubxonasiz).

    <script>, <style> teglarini olib tashlaydi, HTML teglarini olib tashlaydi.
    """
    # Script va style teglarini olib tashlash
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # HTML commentlarini olib tashlash
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    # HTML teglarini olib tashlash
    text = re.sub(r"<[^>]+>", " ", text)
    # HTML entity larni oddiy almashtirishlar
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&nbsp;", " ")
    text = text.replace("&#39;", "'")
    # Ko'p bo'sh joylarni bitta qilish
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_title(html: str) -> str:
    """HTML dan <title> tegini ajratish."""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


class WebReaderTool(Tool):
    """Web sahifani o'qish tool — URL bo'yicha matn olish.

    Bo'lim 7: haqiqiy HTTP so'rov (httpx). Stub rejimda mock qaytaradi.
    """

    def __init__(self, *, stub: bool = True) -> None:
        """Args:
        stub: True bo'lsa, haqiqiy HTTP so'rov yubormaydi (test uchun).
        """
        self._stub = stub

    @property
    def name(self) -> str:
        return "web.read"

    @property
    def description(self) -> str:
        return "Veb sahifani o'qish — URL bo'yicha matn olish (natija UNTRUSTED)"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "O'qiladigan veb sahifa URL",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maksimal belgilar soni (default: 5000)",
                    "default": 5000,
                    "minimum": 100,
                    "maximum": 50000,
                },
            },
            "required": ["url"],
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
        return 15

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        url = params["url"]
        max_chars = params.get("max_chars", 5000)

        # URL validatsiyasi
        validated_url = _validate_url(url)

        if self._stub:
            return self._stub_response(validated_url, max_chars)

        return await self._real_fetch(validated_url, max_chars)

    def _stub_response(self, url: str, _max_chars: int) -> dict[str, Any]:
        """Stub javob — test va development uchun."""
        parsed = urlparse(url)
        return {
            "url": url,
            "title": f"Sahifa: {parsed.hostname}",
            "text": f"{parsed.hostname} sahifasidagi matn (stub). "
            f"Haqiqiy kontent Bo'lim 7 produksiyada.",
            "char_count": 80,
            "truncated": False,
            "source": "web.read (stub)",
            "trust_level": "UNTRUSTED",
        }

    async def _real_fetch(self, url: str, max_chars: int) -> dict[str, Any]:
        """Haqiqiy HTTP so'rov — httpx bilan."""
        try:
            import httpx
        except ImportError as exc:
            raise ToolError("httpx kutubxonasi o'rnatilmagan: pip install httpx") from exc

        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                follow_redirects=True,
                max_redirects=5,
            ) as client:
                resp = await client.get(
                    url,
                    headers={"User-Agent": "ZET/1.0 (web.read tool)"},
                )
                resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ToolError(f"Sahifa yuklanmadi (timeout): {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise ToolError(f"HTTP xato: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise ToolError(f"So'rov xatosi: {exc}") from exc

        # Hajm tekshiruvi
        content_length = len(resp.content)
        if content_length > _MAX_CONTENT_BYTES:
            raise ToolError(
                f"Sahifa juda katta: {content_length} bayt (max {_MAX_CONTENT_BYTES} bayt)"
            )

        html = resp.text
        title = _extract_title(html)
        text = _extract_text(html)

        # Truncate
        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars] + "..."

        return {
            "url": url,
            "title": title,
            "text": text,
            "char_count": len(text),
            "truncated": truncated,
            "source": "web.read",
            "trust_level": "UNTRUSTED",
        }
