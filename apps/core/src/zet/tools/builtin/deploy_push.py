"""deploy.push — statik sayt fayllarini lokal generatsiya qilish (Z1.10).

MINIMAL AMALGA OSHIRISH (BLOCK-3 audit, F8). NEGA cheklangan:
`website`/`deployment` capability'lari ilgari `deploy.push`ga tayanardi,
lekin bu tool ToolRegistry'da HECH QAYERDA ro'yxatdan o'tmagan edi — ZET
"sayt qur" so'roviga hech qanday real ish qilolmasdi (audit topgan gap).

Bu tool FAQAT quyidagini qiladi:
    1. Berilgan fayllarni (HTML/CSS/JS/JSON/SVG/MD/TXT — matn fayllar)
       lokal diskka `<sites_dir>/<site_name>/` papkasiga yozadi
    2. Lokal preview uchun aniq ko'rsatma qaytaradi (masalan
       `python -m http.server` bilan shu papkani serve qilish)

Bu tool QILMAYDIGAN narsa (KEYINGI BOSQICH, hali yo'q):
    - Haqiqiy hosting/domain ulanishi (Vercel/Netlify/S3/Hetzner static)
    - DNS/SSL sozlash
    - CI/CD, build pipeline (Next.js/Vite build)
    - Rasm/binary fayl yuklash

Natija javobida bu ochiq ko'rsatiladi: `hosting: "NOT_IMPLEMENTED"` —
hech qachon "sayt jonli" degan yolg'on da'vo qilinmaydi (PART 8, "never
fake autonomy").

Ruxsat: WRITE — fayl yaratadi/o'zgartiradi (real remote push emas).
Trust: SYSTEM — ichki tool, tashqi kirishga bog'liq emas.
Idempotent: ha — bir xil site_name bilan qayta yozilsa ustidan yoziladi.

Xavfsizlik:
    - Path traversal oldini oladi (`_vault.py`dagi bir xil sanitizatsiya
      naqshi — site_name va har bir fayl yo'li alohida tekshiriladi)
    - Fayl kengaytmasi allowlist (faqat matn/veb formatlar)
    - Fayl soni va umumiy hajm chegaralangan

Bog'liq qarorlar:
    V-31 — WRITE ruxsat darajasi
    PART 8 — halol yiqilish / never fake autonomy
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

from zet.domain.enums import PermissionLevel
from zet.tools.base import Tool, ToolError
from zet.tools.builtin._vault import sanitize_segment, sanitize_title

log = structlog.get_logger(__name__)

_MAX_FILES = 30
"""Bitta deploy'da yozilishi mumkin bo'lgan fayllar soni chegarasi."""

_MAX_FILE_BYTES = 200 * 1024  # 200 KB
"""Bitta fayl hajmi chegarasi."""

_MAX_TOTAL_BYTES = 2 * 1024 * 1024  # 2 MB
"""Butun sayt umumiy hajmi chegarasi."""

_ALLOWED_EXTENSIONS = frozenset(
    {".html", ".htm", ".css", ".js", ".mjs", ".json", ".svg", ".md", ".txt", ".xml", ".webmanifest"}
)
"""Faqat matn/veb formatlar — rasm/binary fayllar hali qo'llab-quvvatlanmaydi
(keyingi bosqich: base64 yoki alohida asset yuklash yo'li)."""


class DeployPushTool(Tool):
    """Statik sayt fayllarini lokal diskka yozadi (MINIMAL — real hosting yo'q)."""

    def __init__(self, *, sites_dir: Path) -> None:
        self._sites_dir = sites_dir.resolve()

    @property
    def name(self) -> str:
        return "deploy.push"

    @property
    def description(self) -> str:
        return (
            "Sayt fayllarini (HTML/CSS/JS) lokal diskka yozadi va lokal preview "
            "ko'rsatmasini qaytaradi. DIQQAT: bu HALI haqiqiy hosting/domain'ga "
            "chiqarmaydi — faqat fayl generatsiya + lokal ko'rish. Real deploy "
            "keyingi bosqich."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "site_name": {
                    "type": "string",
                    "description": (
                        "Sayt papkasi nomi (masalan 'mening-saytim'). Ichki "
                        "papka bilan ham bo'lishi mumkin."
                    ),
                    "minLength": 1,
                    "maxLength": 200,
                },
                "files": {
                    "type": "object",
                    "description": (
                        "Nisbiy yo'l → fayl matni. Masalan: "
                        '{"index.html": "<html>...</html>", "style.css": "body {...}"}. '
                        "Faqat matn formatlar: .html/.css/.js/.json/.svg/.md/.txt/.xml"
                    ),
                    "additionalProperties": {"type": "string"},
                    "minProperties": 1,
                },
            },
            "required": ["site_name", "files"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.WRITE

    @property
    def idempotent(self) -> bool:
        return True

    @property
    def timeout_s(self) -> int:
        return 15

    def _resolve_site_dir(self, site_name: str) -> Path:
        safe_name = sanitize_title(site_name)
        root = self._sites_dir
        site_dir = (root / safe_name).resolve()
        if not site_dir.is_relative_to(root):
            raise ToolError(f"Xavfsizlik: sayt yo'li sites papkasidan tashqarida: {site_name}")
        return site_dir

    @staticmethod
    def _resolve_file_path(site_dir: Path, rel_path: str) -> Path:
        raw_parts = [p for p in rel_path.replace("\\", "/").split("/") if p.strip()]
        if not raw_parts:
            raise ToolError(f"Yaroqsiz fayl yo'li: {rel_path!r}")
        safe_parts = [sanitize_segment(p) for p in raw_parts]
        file_path = (site_dir / Path(*safe_parts)).resolve()
        if not file_path.is_relative_to(site_dir):
            raise ToolError(f"Xavfsizlik: fayl yo'li sayt papkasidan tashqarida: {rel_path}")
        return file_path

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        site_name: str = params["site_name"]
        files: dict[str, Any] = params["files"]

        if not files:
            raise ToolError("Kamida bitta fayl kerak")
        if len(files) > _MAX_FILES:
            raise ToolError(f"Fayllar soni {_MAX_FILES} tadan oshmasligi kerak")

        # Validatsiya — kengaytma, hajm, umumiy hajm (yozishdan OLDIN,
        # qisman yozilgan sayt qolib ketmasin).
        total_bytes = 0
        for rel_path, content in files.items():
            if not isinstance(content, str):
                raise ToolError(f"Fayl matni string bo'lishi kerak: {rel_path!r}")
            ext = Path(rel_path).suffix.lower()
            if ext not in _ALLOWED_EXTENSIONS:
                allowed = ", ".join(sorted(_ALLOWED_EXTENSIONS))
                raise ToolError(
                    f"Qo'llab-quvvatlanmaydigan fayl turi: {rel_path!r} "
                    f"(faqat: {allowed})"
                )
            size = len(content.encode("utf-8"))
            if size > _MAX_FILE_BYTES:
                raise ToolError(
                    f"Fayl {rel_path!r} {_MAX_FILE_BYTES // 1024} KB dan katta"
                )
            total_bytes += size
        if total_bytes > _MAX_TOTAL_BYTES:
            raise ToolError(
                f"Umumiy sayt hajmi {_MAX_TOTAL_BYTES // 1024 // 1024} MB dan katta"
            )

        site_dir = self._resolve_site_dir(site_name)
        site_dir.mkdir(parents=True, exist_ok=True)

        written: list[str] = []
        for rel_path, content in files.items():
            file_path = self._resolve_file_path(site_dir, rel_path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            written.append(str(file_path.relative_to(self._sites_dir)))

        has_index = "index.html" in files or any(
            rel.endswith("/index.html") for rel in files
        )

        return {
            # HALOL: bu maydon hech qachon True bo'lmaydi — real remote
            # push/hosting hali amalga oshirilmagan (PART 8).
            "deployed": False,
            "hosting": "NOT_IMPLEMENTED",
            "action": "files_generated",
            "site_name": site_name,
            "path": str(site_dir),
            "files_written": written,
            "total_bytes": total_bytes,
            "preview_hint": (
                f"Lokal ko'rish uchun: cd {site_dir} && python -m http.server 8080 "
                "— keyin brauzerda http://localhost:8080 oching."
                if has_index
                else (
                    "index.html topilmadi — brauzerda ochish uchun kamida bitta "
                    "index.html fayl kerak."
                )
            ),
        }


__all__ = ["DeployPushTool"]
