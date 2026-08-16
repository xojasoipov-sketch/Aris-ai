"""EvidenceProvider — TaskGraph uchun HAQIQIY tashqi holat dalili (JB-15 PART I).

AUDIT TOPILMASI (JB-14'da ATAYLAB qoldirilgan, JB-15 endi yopadi):
`TaskGraphExecutor._verify_task_result()` (JB-14) mavjud `Verifier`ni
chaqirar edi, LEKIN unga uzatilgan "tool natijasi" aslida
`AgentRunResult.output` — agentning O'Z SO'ZI bilan yozgan YAKUNIY matn
xulosasi edi, tool'ning haqiqiy strukturaviy qaytish qiymati (masalan
`{"path": "...", "size_bytes": 128}` yoki `{"message_id": 123}`) EMAS.
Bu — "tool javobini ishonib qabul qilish"ning FAQAT bir qadam nariga
surilgan shakli edi ("agentning tool haqidagi HIKOYASINI ishonib qabul
qilish"). Haqiqiy tashqi holat HECH QACHON so'ralmagan edi.

Bu modul buni tuzatadi: `AgentRunResult.tool_results` (JB-15,
`domain/agent.py`) orqali HAR bir tool chaqiruvining XOM natijasiga
kirish ochiladi, `EvidenceProvider` esa shu xom natijadan (yoki
kerak bo'lsa MUSTAQIL so'rov — masalan GitHub `GET`) HAQIQIY, tekshirib
bo'ladigan `Evidence` quradi. `TaskGraphExecutor._verify_task_result()`
(task_graph.py) bu dalilni — mavjud bo'lsa — eski (JB-14, agent-matn-
asoslangan) yo'ldan USTUN qo'yadi.

Konseptual oqim (spec §PART I):
    Action → Tool → External State → Evidence Query → Verifier

MUHIM CHEKLOV (ATAYLAB, ochiq e'lon qilingan): bu — YANGI, RAQOBATDOSH
`Verifier` EMAS. `Evidence` faqat operatsion faktlarni (manba, holat,
vaqt, avtoritativlik, ishonch) saqlaydi — hech qanday fikrlash zanjiri,
hech qanday LLM chaqiruvi. Provider yo'q bo'lgan tool'lar uchun eski
(JB-14) Verifier yo'li o'zgarmagan qoladi (regression yo'q).

Bog'liq qarorlar:
    JB-15 PART I — real-world grounding
    JB-14 PART I — mavjud Verifier/VerificationOutcome (bu yerda QAYTA
        QURILMAYDI, faqat haqiqiy dalil bilan oziqlantiriladi)
    A-05 — tashqi manba natijasi ishonch darajasi bilan keladi
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Protocol

import structlog

from zet.db.base import utcnow

log = structlog.get_logger(__name__)


class EvidenceState(StrEnum):
    """Tashqi holat so'rovining natijasi — spec §15 UNCERTAIN oqimidagi
    uchta tarmoqqa mos keladi (FOUND/NOT_FOUND/UNKNOWN)."""

    FOUND = "found"
    """Kutilgan tashqi holat TOPILDI (masalan fayl mavjud, issue ochiq)."""

    NOT_FOUND = "not_found"
    """Tashqi holat SO'RALDI va ANIQ topilmadi (masalan fayl yo'q)."""

    UNKNOWN = "unknown"
    """So'rovning o'zi natija bermadi (tarmoq xatosi, API cheklovi,
    kutilmagan shakl) — "topilmadi" DEGANI EMAS, "bila olmadik" degani."""


@dataclass(frozen=True, slots=True)
class Evidence:
    """Operatsion dalil — spec §7 shartnomasi.

    ATAYLAB YO'Q: fikrlash zanjiri, xom LLM javoblari, kredensiallar.
    Faqat tekshirib bo'ladigan faktlar."""

    source: str
    """Dalil manbasi (masalan "filesystem", "github", "telegram")."""

    state: EvidenceState

    observed_state: dict[str, Any] = field(default_factory=dict)
    """Kuzatilgan strukturaviy holat (masalan `{"exists": True, "size_bytes": 128}`)."""

    timestamp: datetime = field(default_factory=utcnow)

    authoritative: bool = False
    """`True` — bu HAQIQIY tashqi tizimdan (fayl tizimi, GitHub API, ...)
    kelgan, ishonchli manba. `False` — taxminiy/mustaqil tekshirib
    bo'lmagan (masalan provider ichki xatoga uchragan)."""

    confidence: float = 0.0
    """0.0-1.0 — `core.verifier.UNCERTAIN_CONFIDENCE_THRESHOLD` bilan
    bir xil shkala (mavjud Verifier confidence tushunchasi qayta
    ishlatiladi, YANGISI ixtiro qilinmaydi)."""

    reason: str = ""
    """Qisqa, operatsion izoh (audit/log uchun) — chain-of-thought EMAS."""


class EvidenceProvider(Protocol):
    """Bitta tool(lar) guruhi uchun tashqi holat so'rovchisi.

    NEGA Protocol: boshqa ixtiyoriy DI komponentlar (`AgentSelectorLike`,
    `AgentProvisionerLike`) bilan bir xil naqsh — chaqiruvchi shakl
    kerak, konkret sinf emas."""

    def supports(self, tool_name: str) -> bool:  # pragma: no cover — protocol
        """Bu provider `tool_name` uchun dalil bera oladimi."""
        ...

    async def observe(
        self, *, tool_name: str, tool_output: Any
    ) -> Evidence:  # pragma: no cover — protocol
        """`tool_output` — tool'ning XOM (agent paraphrase EMAS) natijasi.

        Providerlar MUSTAQIL so'rov ham yuborishi mumkin (masalan GitHub
        `GET`) — `tool_output` shunchaki so'rov uchun kerakli identifikator
        (masalan issue raqami)ni beradi."""
        ...


class EvidenceProviderRegistry:
    """`ToolRegistry` bilan bir xil ruhda — oddiy, tartiblangan qidiruv.

    NEGA alohida registry, `ToolRegistry`ning O'ZI EMAS (spec: "Do NOT
    create a second ToolRegistry"): bu ikkinchi ToolRegistry EMAS — u
    hech qanday `Tool`ni saqlamaydi/bajarmaydi, faqat "qaysi provider
    qaysi tool NATIJASINI tekshira oladi" degan alohida, kichik
    xaritalash. `Tool`larning o'zi hamon BITTA `ToolRegistry`da."""

    def __init__(self, providers: list[EvidenceProvider] | None = None) -> None:
        self._providers: list[EvidenceProvider] = list(providers or [])

    def register(self, provider: EvidenceProvider) -> None:
        self._providers.append(provider)

    def for_tool(self, tool_name: str) -> EvidenceProvider | None:
        """Birinchi mos provider — topilmasa `None` (chaqiruvchi eski
        Verifier yo'liga tushadi, HECH QACHON soxta VERIFIED emas)."""
        for provider in self._providers:
            if provider.supports(tool_name):
                return provider
        return None


def _stat_file(path: Path) -> tuple[bool, int]:
    """Sinxron fayl tizimi so'rovi — `asyncio.to_thread()` orqali chaqiriladi."""
    if not path.is_file():
        return False, 0
    return True, path.stat().st_size


def _unknown(source: str, reason: str, observed_state: dict[str, Any] | None = None) -> Evidence:
    return Evidence(
        source=source,
        state=EvidenceState.UNKNOWN,
        observed_state=observed_state or {},
        authoritative=False,
        confidence=0.0,
        reason=reason,
    )


# ── 1. Filesystem (spec §2) ─────────────────────────────────────────


class FilesystemEvidenceProvider:
    """`note.write` — HAQIQIY fayl tizimi holatini tekshiradi.

    `note.write`ning o'z chiqishi ALLAQACHON hal qiluvchi identifikator
    (`path`, `size_bytes`) beradi — mustaqil qidiruv shart emas, faqat
    HAQIQIY `pathlib.Path` operatsiyasi bilan tekshiriladi (agentning
    "fayl yaratdim" degan so'ziga emas).

    CHEKLOV (ochiq e'lon qilingan): repo'da `note.delete`/`note.move`
    tool'i YO'Q (audit qilindi — faqat write/read/list mavjud), shuning
    uchun spec §2'ning DELETE/MOVE qismlari uchun provider yo'q (tool'ning
    o'zi yo'q — ATAYLAB "yo'q API ixtiro qilinmadi")."""

    _SUPPORTED = frozenset({"note.write"})

    def supports(self, tool_name: str) -> bool:
        return tool_name in self._SUPPORTED

    async def observe(self, *, tool_name: str, tool_output: Any) -> Evidence:
        del tool_name  # Protocol imzosi uchun — bu provider bitta tool bilan ishlaydi
        if not isinstance(tool_output, dict) or "path" not in tool_output:
            return _unknown("filesystem", "tool natijasida 'path' maydoni yo'q")

        path = Path(str(tool_output["path"]))
        try:
            # ASYNC240: sinxron fayl tizimi so'rovi thread'ga chiqariladi
            # (`devices/rtsp.py`dagi bilan bir xil naqsh) — event loop
            # bloklanmaydi.
            exists, actual_size = await asyncio.to_thread(_stat_file, path)
        except OSError as exc:
            return _unknown("filesystem", f"fayl tizimi xatosi: {exc}", {"path": str(path)})

        if not exists:
            return Evidence(
                source="filesystem",
                state=EvidenceState.NOT_FOUND,
                observed_state={"path": str(path), "exists": False},
                authoritative=True,
                confidence=0.95,
                reason="kutilgan fayl haqiqiy fayl tizimida mavjud emas",
            )

        expected_size = tool_output.get("size_bytes")
        size_matches = expected_size is None or actual_size == expected_size
        return Evidence(
            source="filesystem",
            state=EvidenceState.FOUND if size_matches else EvidenceState.UNKNOWN,
            observed_state={"path": str(path), "exists": True, "size_bytes": actual_size},
            authoritative=True,
            confidence=0.95 if size_matches else 0.5,
            reason=(
                "fayl haqiqiy fayl tizimida mavjud, hajm mos"
                if size_matches
                else f"fayl mavjud, lekin hajm mos kelmadi (kutilgan={expected_size}, "
                f"haqiqiy={actual_size})"
            ),
        )


# ── 2. GitHub (spec §3) ──────────────────────────────────────────────


class GitHubEvidenceProvider:
    """`github.write` — MAVJUD `GitHubReadTool` orqali HAQIQIY GitHub
    holatini so'raydi (yangi HTTP klient/token QURILMAYDI — bir xil
    tool nusxasi, `api/deps.py`da ro'yxatdan o'tgani, qayta ishlatiladi).

    CHEKLOV (ochiq e'lon qilingan): `GitHubReadTool` bitta-comment GET
    amalini QO'LLAB-QUVVATLAMAYDI (faqat `get_issue`/`get_pr`/
    `list_issues`/`get_file`) — shu sabab `add_comment` uchun mustaqil
    tekshiruv MUMKIN EMAS, natija UNKNOWN (spec: "Do not verify by
    trusting tool output alone" — lekin mavjud API yetarli emas, shuning
    uchun soxta VERIFIED o'rniga HALOL UNKNOWN qaytariladi)."""

    _NUMBERED_ACTIONS: ClassVar[dict[str, str]] = {
        "create_issue": "get_issue",
        "create_pr": "get_pr",
    }

    def __init__(self, read_tool: Any) -> None:
        self._read_tool = read_tool

    def supports(self, tool_name: str) -> bool:
        return tool_name == "github.write"

    async def observe(self, *, tool_name: str, tool_output: Any) -> Evidence:
        del tool_name  # Protocol imzosi uchun — bu provider bitta tool bilan ishlaydi
        if not isinstance(tool_output, dict):
            return _unknown("github", "tool natijasi kutilmagan shaklda")

        action = tool_output.get("action")
        repo = tool_output.get("repo")
        number = tool_output.get("number")
        read_action = self._NUMBERED_ACTIONS.get(str(action))

        if read_action is None or not repo or number is None:
            return _unknown(
                "github",
                f"'{action}' uchun mustaqil GET amali mavjud emas "
                "(faqat create_issue/create_pr tekshiriladi)",
                {"action": action},
            )

        try:
            read_result = await self._read_tool.execute(
                {"action": read_action, "repo": repo, "number": number}
            )
        except Exception as exc:
            return _unknown("github", f"GitHub GET so'rovi xato berdi: {exc}", {"repo": repo, "number": number})

        if not read_result.success or not isinstance(read_result.output, dict):
            return Evidence(
                source="github",
                state=EvidenceState.NOT_FOUND,
                observed_state={"repo": repo, "number": number},
                authoritative=True,
                confidence=0.85,
                reason=read_result.error or "GitHub GET muvaffaqiyatsiz — obyekt topilmadi",
            )

        found_number = read_result.output.get("number")
        matches = found_number == number
        return Evidence(
            source="github",
            state=EvidenceState.FOUND if matches else EvidenceState.NOT_FOUND,
            observed_state={
                "repo": repo,
                "number": found_number,
                "state": read_result.output.get("state"),
            },
            authoritative=True,
            confidence=0.95 if matches else 0.3,
            reason="GitHub API real obyektni tasdiqladi" if matches else "raqam mos kelmadi",
        )


# ── 3. Telegram (spec §4) ─────────────────────────────────────────────


class TelegramEvidenceProvider:
    """`telegram.channel_post` — Bot API'da BITTA xabarni keyinroq GET
    qilish AMALI YO'Q (rasmiy, hujjatlashtirilgan cheklov — `getMessage`
    Bot API'da mavjud emas). Shu sabab bu provider MUSTAQIL so'rov
    YUBORMAYDI — o'rniga `sendMessage`ning o'z HAQIQIY, Telegram
    serveridan qaytgan `message_id` maydonidan (agentning erkin matn
    xulosasi EMAS — tool'ning strukturaviy javobi) foydalanadi.

    Spec §4: "If the API cannot reliably inspect the message: return
    UNCERTAIN." — `message_id` mavjud bo'lsa, bu YUBORISH tasdiqlangani
    haqida haqiqiy dalil (Telegram o'zi ID bergan), lekin XABARNING
    HALI HAM MAVJUDLIGINI (masalan o'chirilmaganini) tasdiqlay olmaymiz
    — shu sabab confidence pastroq (0.85, `VERIFIED` chegarasidan
    yuqori, lekin fayl-tizimi darajasidagi qat'iyatdan past) qo'yiladi."""

    def supports(self, tool_name: str) -> bool:
        return tool_name == "telegram.channel_post"

    async def observe(self, *, tool_name: str, tool_output: Any) -> Evidence:
        del tool_name  # Protocol imzosi uchun — bu provider bitta tool bilan ishlaydi
        if not isinstance(tool_output, dict):
            return _unknown("telegram", "tool natijasi kutilmagan shaklda")

        posted = bool(tool_output.get("posted"))
        message_id = tool_output.get("message_id")
        if posted and message_id:
            return Evidence(
                source="telegram",
                state=EvidenceState.FOUND,
                observed_state={"message_id": message_id, "chat_id": tool_output.get("chat_id")},
                authoritative=True,
                confidence=0.85,
                reason=(
                    "Telegram API haqiqiy message_id qaytardi (sendMessage "
                    "natijasi) — Bot API'da keyinchalik alohida GET imkoni yo'q"
                ),
            )
        return Evidence(
            source="telegram",
            state=EvidenceState.NOT_FOUND,
            observed_state={"posted": posted, "message_id": message_id},
            authoritative=True,
            confidence=0.7,
            reason="'posted' belgisi False yoki message_id qaytmadi",
        )


# ── 4. HTTP/API — Instagram misoli (spec §5) ──────────────────────────


class InstagramEvidenceProvider:
    """`instagram.publish_photo` — WRITE → GET namunasi (spec §5): yangi
    postni MAVJUD `instagram.recent_media` (READ) tool orqali qidiradi.

    Bu — repo'dagi eng aniq "HTTP/API WRITE keyin GET bilan tekshirish"
    namunasi: ikkalasi ham allaqachon mavjud, faqat ULANMAGAN edi."""

    def __init__(self, recent_media_tool: Any) -> None:
        self._recent_media_tool = recent_media_tool

    def supports(self, tool_name: str) -> bool:
        return tool_name == "instagram.publish_photo"

    async def observe(self, *, tool_name: str, tool_output: Any) -> Evidence:
        del tool_name  # Protocol imzosi uchun — bu provider bitta tool bilan ishlaydi
        if not isinstance(tool_output, dict):
            return _unknown("instagram", "tool natijasi kutilmagan shaklda")

        posted = bool(tool_output.get("posted"))
        media_id = tool_output.get("media_id")
        if not posted or not media_id:
            return Evidence(
                source="instagram",
                state=EvidenceState.NOT_FOUND,
                observed_state={"posted": posted},
                authoritative=True,
                confidence=0.7,
                reason="'posted' belgisi False yoki media_id qaytmadi",
            )

        try:
            read_result = await self._recent_media_tool.execute({"limit": 25})
        except Exception as exc:
            return _unknown("instagram", f"recent_media so'rovi xato berdi: {exc}", {"media_id": media_id})

        if not read_result.success or not isinstance(read_result.output, dict):
            return _unknown("instagram", "recent_media muvaffaqiyatsiz", {"media_id": media_id})

        media_list = read_result.output.get("media", [])
        found = any(item.get("id") == media_id for item in media_list)
        return Evidence(
            source="instagram",
            state=EvidenceState.FOUND if found else EvidenceState.NOT_FOUND,
            observed_state={"media_id": media_id, "recent_count": len(media_list)},
            authoritative=True,
            confidence=0.9 if found else 0.4,
            reason=(
                "post recent_media ro'yxatida topildi"
                if found
                else "post recent_media ro'yxatida topilmadi (tarqatish kechikishi yoki "
                "muvaffaqiyatsizlik bo'lishi mumkin)"
            ),
        )


# ── 5. Camera (spec §6) ───────────────────────────────────────────────


class CameraEvidenceProvider:
    """`camera.snapshot` — tool'ning O'Z strukturaviy natijasidagi
    metama'lumotni (`has_image`, `image_b64`, `width`, `height`)
    deterministik tekshiradi (agentning "rasm oldim" degan matn
    xulosasiga emas).

    CHEKLOV (ochiq e'lon qilingan): repo'da PTZ (pan-tilt-zoom) tool'i
    YO'Q — spec §6'ning PTZ qismi uchun provider YO'Q (ixtiro qilinmadi)."""

    def supports(self, tool_name: str) -> bool:
        return tool_name == "camera.snapshot"

    async def observe(self, *, tool_name: str, tool_output: Any) -> Evidence:
        del tool_name  # Protocol imzosi uchun — bu provider bitta tool bilan ishlaydi
        if not isinstance(tool_output, dict):
            return _unknown("camera", "tool natijasi kutilmagan shaklda")

        has_image = bool(tool_output.get("has_image"))
        image_b64 = tool_output.get("image_b64") or ""
        width = tool_output.get("width") or 0
        height = tool_output.get("height") or 0
        valid = has_image and len(image_b64) > 0 and width > 0 and height > 0

        return Evidence(
            source="camera",
            state=EvidenceState.FOUND if valid else EvidenceState.NOT_FOUND,
            observed_state={
                "has_image": has_image,
                "width": width,
                "height": height,
                "image_b64_len": len(image_b64),
            },
            authoritative=True,
            confidence=0.9 if valid else 0.3,
            reason="snapshot metadata yaroqli" if valid else "snapshot metadata to'liq emas/yaroqsiz",
        )


__all__ = [
    "CameraEvidenceProvider",
    "Evidence",
    "EvidenceProvider",
    "EvidenceProviderRegistry",
    "EvidenceState",
    "FilesystemEvidenceProvider",
    "GitHubEvidenceProvider",
    "InstagramEvidenceProvider",
    "TelegramEvidenceProvider",
]
