"""GitHub Intelligence — normallashtirilgan manba modeli (spec Bo'lim 2/3/4).

`integrations/public_apis/catalog/models.py::PublicAPIEntry`ning bir xil
falsafasi: xom repo emas, ZET ICHIDA barqaror, tekshiriladigan model.
Farq — bu yerda yozuvlar avtomatik PARSE qilinmaydi (public-apis'ning
1500+ qatorli README'sidan farqli, bu atigi 9 ta qo'lda ko'rib chiqilgan
repo) — `seed.py`da qo'lda yoziladi, har biri ushbu audit sessiyasida
HAQIQATAN o'qilgan/tekshirilgan asosida.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class SourceType(StrEnum):
    """Manba QANDAY turdagi narsa (hozircha faqat GitHub repo'lar)."""

    GITHUB_REPOSITORY = "github_repository"


class SourceCategory(StrEnum):
    """Mavzu tegi — audit hujjatlarida guruhlash uchun."""

    AI_AGENT = "ai_agent"
    API_CATALOG = "api_catalog"
    SYSTEM_DESIGN = "system_design"
    ENGINEERING_REFERENCE = "engineering_reference"
    ALGORITHMS_CS = "algorithms_cs"
    LEARNING_RESOURCES = "learning_resources"
    KNOWLEDGE_BASE = "knowledge_base"


class TrustLevel(StrEnum):
    """Bo'lim 3 — mashhurlik (yulduz) XAVFSIZLIK kafolati EMAS.

    Har bir daraja — ushbu repo ustida ZET tomonidan QILINGAN ishning
    aksi, repo'ning o'z obro'sining emas:
    """

    UNTRUSTED_CODE = "untrusted_code"
    """Ko'rib chiqilmagan — kod HECH QACHON ishga tushirilmaydi."""

    EXTERNAL_SOURCE = "external_source"
    """Faqat bilim/havola manbai sifatida ko'rib chiqilgan (masalan
    kitob/repo ro'yxati) — o'z kodi umuman baholanmagan."""

    VERIFIED_SOURCE = "verified_source"
    """Chuqur audit qilingan (arxitektura/xavfsizlik/litsenziya) —
    lekin kod hali ZET ichida ijro etilmaydi (masalan OpenClaw:
    naqshlar o'rganildi, kod nusxalanmadi)."""

    TRUSTED_REFERENCE = "trusted_reference"
    """Chuqur audit qilingan VA undan olingan naqsh/ma'lumot ZET
    ICHIDA haqiqiy, ko'rib chiqilgan kod sifatida qo'llanildi (masalan
    public-apis: katalog ma'lumoti `integrations/public_apis/`ga
    aylandi)."""


class IntegrationAction(StrEnum):
    """Spec Bo'lim 8 — ruxsat etilgan yakuniy qarorlar (repo darajasida
    UMUMIY xulosa; komponent-darajasidagi mayda farqlar
    `docs/audits/GITHUB_REPOSITORY_INTEGRATION_MATRIX.md`da)."""

    KEEP = "keep"
    """ZET'niki allaqachon yaxshiroq/yetarli — o'zgarish yo'q."""

    ADAPT = "adapt"
    """Naqsh o'rganildi va ZET'ning O'Z kodiga moslashtirilib qo'llanildi."""

    IMPROVE = "improve"
    """Mavjud ZET komponenti shu topilma asosida yaxshilandi."""

    INTEGRATE = "integrate"
    """Haqiqiy, ijro etiladigan integratsiya qurildi (public-apis kabi)."""

    REFERENCE_ONLY = "reference_only"
    """Faqat bilim manbai — Research Agent orqali so'rov vaqtida
    o'qiladi, ZET kodiga HECH NARSA ko'chirilmaydi."""

    IGNORE = "ignore"
    """Ko'rib chiqildi, lekin foydali/mos emas deb topildi."""


def source_id(repository: str) -> str:
    """Barqaror, deterministik ID — `entry_id()` bilan bir xil naqsh
    (`public_apis/catalog/models.py`)."""
    return hashlib.sha256(repository.strip().lower().encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class KnowledgeSource:
    """Bitta ko'rib chiqilgan GitHub repozitoriysining normallashtirilgan
    tasviri (spec Bo'lim 2's `KnowledgeSource` konseptual modeli)."""

    id: str
    repository: str
    """`owner/name` formatida."""
    name: str
    description: str
    category: SourceCategory
    license: str
    """SPDX identifikatori (masalan 'MIT') yoki 'unknown'."""
    source_type: SourceType
    trust_level: TrustLevel
    capabilities: tuple[str, ...]
    """ZET capability-teglariga o'xshash — bu repo QAYSI sohaga tegishli
    (masalan ("agent", "tools", "memory", "automation"))."""
    documentation_url: str
    integration_action: IntegrationAction | None = None
    notes: str = ""
    """Audit xulosasi — bitta-ikkita jumlada NEGA shu trust/action
    tanlangani (halollik: qaror asossiz ko'rinmasin)."""
    last_synced: datetime | None = None
    version: str | None = None
    """Tekshirilgan commit SHA yoki teg (mavjud bo'lsa) — repo o'zgarib
    ketsa, bu audit QAYSI holatga tegishli ekanini bilish uchun."""
    enabled: bool = True
    code_executable: bool = False
    """QAT'IY DEFAULT (spec Bo'lim 4): repo kodi ISHGA TUSHIRILMAYDI.
    Faqat `integrations/public_apis/adapters/` kabi qo'lda yozilgan,
    ko'rib chiqilgan ZET kodi `True`ga ega bo'lishi mumkin — bu maydon
    "repo kodi ishlaydi" degani emas, "ZETda ushbu repo'dan kelib
    chiqqan HAQIQIY ijro etiluvchi kod bor" degani."""
    metadata: dict[str, str] = field(default_factory=dict)


__all__ = [
    "IntegrationAction",
    "KnowledgeSource",
    "SourceCategory",
    "SourceType",
    "TrustLevel",
    "source_id",
]
