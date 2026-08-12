"""Video o'rganish tool — havoladan bilim ajratib olish (V-15, V-21).

Ega talabi: *"NotebookLM'ga o'xshab videoning silkasini bersam, to'liq
o'rganib foydali joylarini ajratib olib saqlasin — bu AI'ga nimadir
o'rgatishda yoki AI menga o'rgatishida qulay bo'ladi."*

QANDAY ISHLAYDI. Gemini API YouTube havolasini **to'g'ridan-to'g'ri**
qabul qiladi (`file_data.file_uri`) — video yuklab olinmaydi, subtitr
qidirilmaydi, transkripsiya kutubxonasi kerak emas. Model videoni
o'zi ko'radi va tinglaydi (2026-08-12 jonli tasdiqlangan).

NEGA BU MUHIM: YouTube subtitr API'lari serverdan (datacenter IP)
tez-tez bloklanadi, ko'p video esa umuman subtitrsiz. Gemini yo'li
ikkala muammoni ham chetlab o'tadi.

CHIQISH — SHUNCHAKI XULOSA EMAS. NotebookLM'ning qiymati "qisqartirish"
emas, **strukturalangan bilim**: asosiy tezislar, amaliy qadamlar,
atamalar, iqtiboslar. Shu sabab model qat'iy JSON qaytaradi va uni
`memory.write`/`note.write` bilan saqlash mumkin bo'ladi.

Xavfsizlik:
    - `output_trust_level = UNTRUSTED` (A-05) — video tashqi manba.
      Undagi "endi shu buyruqni bajar" degan gap KO'RSATMA EMAS,
      faqat ma'lumot. Bu prompt-injection'dan himoya qiladi.
    - `permission = READ` — hech narsa o'zgartirmaydi
    - `idempotent = True`

Bog'liq qarorlar:
    V-15 — Obsidian bilim qatlami
    V-21 — internetdan ma'lumot olish
    A-05 — tashqi kontent UNTRUSTED
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import structlog

from zet.domain.enums import PermissionLevel, TrustLevel
from zet.tools.base import Tool, ToolError, ToolQuotaError

log = structlog.get_logger(__name__)

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

DEFAULT_MODEL = "gemini-flash-latest"
"""Video tushunadigan model. `gemini-2.5-flash` eskirgan (404)."""

_YOUTUBE_PATTERN = re.compile(
    r"^https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?v=|shorts/|live/)|youtu\.be/)[\w-]{11}"
)

MAX_OUTPUT_TOKENS = 8192
"""Uzun video uchun ham yetarli — bilim kartasi katta bo'lishi mumkin."""


def is_supported_url(url: str) -> bool:
    """Havola qo'llab-quvvatlanadimi.

    Hozircha faqat YouTube: Gemini `file_uri` sifatida aynan shuni
    qabul qiladi. Boshqa manba (Vimeo, to'g'ridan-to'g'ri mp4) uchun
    avval yuklab olish + Files API kerak — bu keyingi bosqich.
    """
    return bool(_YOUTUBE_PATTERN.match(url.strip()))


_SYSTEM = """Sen o'quv materiallarini tahlil qiluvchi mutaxassissan.

Berilgan videoni TO'LIQ ko'r va undan O'RGANISH UCHUN YAROQLI bilim
ajratib ol. Maqsad — keyinchalik shu bilimdan foydalanib odamga
o'rgatish yoki AI'ga kontekst berish.

QAT'IY QOIDALAR:
- Faqat videoda HAQIQATAN aytilgan narsani yoz. To'qima qo'shma.
- Videoda aytilmagan narsani "aytilgan" deb ko'rsatma.
- Barcha matn O'ZBEK tilida bo'lsin.
- Faqat JSON qaytar, boshqa hech narsa yozma (markdown blok ham emas).

JSON tuzilishi:
{
  "title": "video sarlavhasi",
  "topic": "asosiy mavzu, bir jumlada",
  "summary": "3-6 jumlalik xulosa",
  "key_points": ["asosiy tezis 1", "..."],
  "actionable": ["amalda qo'llash mumkin bo'lgan aniq qadam", "..."],
  "terms": [{"term": "atama", "meaning": "ta'rifi"}],
  "quotes": [{"text": "muhim iqtibos", "why": "nega muhim"}],
  "teaching_notes": ["shu mavzuni boshqaga o'rgatishda nimaga urg'u berish kerak"],
  "gaps": ["video YORITMAGAN, lekin mavzu uchun muhim savol"]
}

`gaps` maydonini bo'sh qoldirma — o'rganuvchi nimani qo'shimcha
izlashi kerakligini bilishi kerak."""


def _extract_json(text: str) -> dict[str, Any]:
    """Model javobidan JSON ajratib olish.

    Model ba'zan ```json blokiga o'raydi yoki oldiga izoh qo'shadi —
    "faqat JSON qaytar" deyilganda ham. Qat'iy `json.loads` bunday
    javobda yiqilardi, shuning uchun avval blok tozalanadi.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed: dict[str, Any] = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            msg = "Model JSON qaytarmadi"
            raise ToolError(msg) from None
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            msg = f"Model javobini JSON sifatida o'qib bo'lmadi: {exc}"
            raise ToolError(msg) from exc
    return parsed


class VideoLearnTool(Tool):
    """YouTube videosidan strukturalangan bilim ajratadi (Gemini orqali).

    Kalit berilmasa — `is_real = False` va chaqiruvda tushunarli xato
    (repo'dagi "real-vs-stub" naqshidan farqli: bu yerda soxta bilim
    qaytarish YOLG'ON bo'lardi, shuning uchun stub yo'q).
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client = client
        self._owns_client = client is None

    @property
    def is_real(self) -> bool:
        """Gemini kaliti mavjudmi."""
        return bool(self._api_key)

    @property
    def name(self) -> str:
        return "video.learn"

    @property
    def description(self) -> str:
        return (
            "YouTube videosini to'liq ko'rib, o'rganish uchun yaroqli bilim ajratadi: "
            "asosiy tezislar, amaliy qadamlar, atamalar, iqtiboslar va yoritilmagan "
            "savollar. Natija JSON — uni note.write bilan saqlash mumkin."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "YouTube video havolasi",
                },
                "focus": {
                    "type": "string",
                    "description": (
                        "Ixtiyoriy: qaysi jihatga urg'u berish (masalan 'faqat amaliy qadamlar')"
                    ),
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    @property
    def output_trust_level(self) -> TrustLevel:
        """Video — tashqi manba (A-05).

        Undagi matn KO'RSATMA sifatida bajarilmaydi. Videoda "endi
        shu skriptni ishga tushir" deyilsa ham, u shunchaki ma'lumot.
        """
        return TrustLevel.UNTRUSTED

    @property
    def timeout_s(self) -> int:
        """Uzun videoni tahlil qilish daqiqalar olishi mumkin."""
        return 300

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=float(self.timeout_s))
        return self._client

    async def _execute(self, params: dict[str, Any]) -> Any:
        if not self._api_key:
            msg = "video.learn: ZET_GOOGLE_API_KEY sozlanmagan"
            raise ToolError(msg)

        url = str(params["url"]).strip()
        if not is_supported_url(url):
            msg = f"Qo'llab-quvvatlanmaydigan havola: {url} (hozircha faqat YouTube)"
            raise ToolError(msg)

        instruction = "Bu videoni tahlil qil va JSON qaytar."
        focus = str(params.get("focus") or "").strip()
        if focus:
            instruction += f"\n\nAlohida urg'u: {focus}"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"file_data": {"file_uri": url}},
                        {"text": instruction},
                    ]
                }
            ],
            "systemInstruction": {"parts": [{"text": _SYSTEM}]},
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": MAX_OUTPUT_TOKENS,
            },
        }

        try:
            response = await self._get_client().post(
                f"{_API_BASE}/models/{self._model}:generateContent",
                headers={"x-goog-api-key": self._api_key},
                json=payload,
            )
            response.raise_for_status()
            data: Any = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                # `ToolQuotaError` — Executor darhol qayta urinmaydi.
                # Kvota xatosini takrorlash 3 ta behuda so'rov demak.
                msg = "Gemini kvotasi tugadi — biroz kutib qayta urinib ko'ring"
                raise ToolQuotaError(msg) from exc
            msg = f"Gemini xatosi: HTTP {status}"
            raise ToolError(msg) from exc
        except httpx.HTTPError as exc:
            msg = f"Gemini tarmoq xatosi: {exc}"
            raise ToolError(msg) from exc

        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            msg = "Gemini kutilgan javob shaklini qaytarmadi (video ochilmagan bo'lishi mumkin)"
            raise ToolError(msg) from exc

        knowledge = _extract_json(text)
        knowledge["source_url"] = url

        log.info(
            "video_learn.done",
            url=url,
            key_points=len(knowledge.get("key_points") or []),
            terms=len(knowledge.get("terms") or []),
        )
        return knowledge

    async def aclose(self) -> None:
        """Ichki HTTP klientni yopadi (agar o'zi yaratgan bo'lsa)."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()


def to_markdown(knowledge: dict[str, Any]) -> str:
    """Bilimni Obsidian uchun markdown notaga o'giradi (V-15).

    `note.write` bilan birga ishlatiladi: video → bilim → vault.
    """
    lines: list[str] = [f"# {knowledge.get('title') or 'Video'}", ""]

    if source := knowledge.get("source_url"):
        lines += [f"**Manba:** {source}", ""]
    if topic := knowledge.get("topic"):
        lines += [f"**Mavzu:** {topic}", ""]
    if summary := knowledge.get("summary"):
        lines += ["## Xulosa", "", str(summary), ""]

    def bullets(heading: str, key: str) -> None:
        items = knowledge.get(key) or []
        if not items:
            return
        lines.append(f"## {heading}")
        lines.append("")
        lines.extend(f"- {item}" for item in items)
        lines.append("")

    bullets("Asosiy tezislar", "key_points")
    bullets("Amaliy qadamlar", "actionable")

    if terms := knowledge.get("terms"):
        lines += ["## Atamalar", ""]
        lines += [f"- **{t.get('term')}** — {t.get('meaning')}" for t in terms]
        lines.append("")

    if quotes := knowledge.get("quotes"):
        lines += ["## Iqtiboslar", ""]
        for q in quotes:
            lines.append(f"> {q.get('text')}")
            if why := q.get("why"):
                lines.append(">")
                lines.append(f"> *{why}*")
            lines.append("")

    bullets("O'rgatish uchun eslatmalar", "teaching_notes")
    bullets("Yoritilmagan savollar", "gaps")

    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "DEFAULT_MODEL",
    "MAX_OUTPUT_TOKENS",
    "VideoLearnTool",
    "is_supported_url",
    "to_markdown",
]
