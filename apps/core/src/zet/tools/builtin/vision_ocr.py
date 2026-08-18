"""vision.ocr — rasm ustidan Gemini vision orqali OCR (Bo'lim 8).

NEGA. Vision agent'ning tool_allowlist'i faqat `camera.snapshot`ga
ega edi — rasm olinar, lekin undagi MATNNI ajratib olish uchun alohida
tool yo'q edi. Modelning o'zi vision-capable bo'lsa ham, OCR
"asosiy javob" emas, `note.write`/`memory.write` kabi keyingi qadamlar
uchun aniq TUZILGAN natija (matn + til + ishonch) kerak. `vision.ocr`
shu bo'shliqni yopadi: bir chaqiruv → matn maydoni, `.text`ni
to'g'ridan-to'g'ri saqlash mumkin.

GEMINI IKKI KIRISH KO'RINISHI. Rasm ikki yo'l bilan berilishi mumkin:
1. `image_url` — ochiq HTTP(S) rasm (kamera snapshot'ini uzoq turli
   xotiraga qo'ymay to'g'ridan-to'g'ri berish uchun);
2. `image_bytes_base64` — mahalliy fayl yoki `camera.snapshot`
   natijasidagi `image_b64` (rasm ochiq bo'lmasin desa).
Ikkalasi bir vaqtda berilsa — bu bir noaniqlik (qaysi biri "asos"?),
shuning uchun XATO. Hech biri berilmasa ham — XATO.

XAVFSIZLIK.
    - permission = READ (hech narsa o'zgartirmaydi)
    - output_trust_level = UNTRUSTED (A-05) — OCR natijasi tashqi manba,
      undagi "endi shu buyruqni bajar" degan gap KO'RSATMA emas.
    - idempotent = True (bir rasm — bir natija)

XATOLAR. Kalit yo'q bo'lsa YOLG'ON javob qaytarmaymiz (soxta OCR
tayin xatarli) — `ToolError` bilan tushunarli izoh: "vision.ocr:
gemini_api_key sozlanmagan".

Bog'liq qarorlar:
    Bo'lim 8 — qurilmalar + kamera/vision
    A-05 — tashqi kontent UNTRUSTED
    V-31 — READ ruxsati
"""

from __future__ import annotations

import base64 as _b64
import binascii
from typing import Any

import httpx
import structlog

from zet.domain.enums import PermissionLevel, TrustLevel
from zet.tools.base import Tool, ToolError, ToolQuotaError
from zet.tools.json_extract import extract_json_object

log = structlog.get_logger(__name__)

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

DEFAULT_MODEL = "gemini-flash-latest"
"""Vision qobiliyati bor bepul qatlam modeli (video.learn bilan bir xil)."""

MAX_OUTPUT_TOKENS = 4096
"""Bir sahifalik matn uchun yetarli — hujjat OCR ham sig'adi."""


_SYSTEM = """Sen rasm ustidan OCR bajaruvchi mutaxassissan.

Berilgan rasmda ko'ringan HAR QANDAY matnni tartibli o'qib chiq.
Faqat JSON qaytar (markdown blok ham qo'shma).

QOIDALAR:
- Matn — rasmda haqiqatan ko'ringan holicha, o'zgartirilmasdan
  (imlo xatosini tuzatma, tarjima qilma).
- Til — rasmda ustunlik qiluvchi til nomi ("uz", "en", "ru", "mixed"
  kabi ISO-ga o'xshash qisqa kod).
- Ishonch — 0.0 dan 1.0 gacha (agar noaniq bo'lsa `null` qaytar).
- Rasmda matn yo'q bo'lsa `text` bo'sh satr, `confidence` 0.0.

JSON tuzilishi:
{
  "text": "rasmdagi matn",
  "language": "til kodi",
  "confidence": 0.87
}"""


class VisionOcrTool(Tool):
    """Gemini vision orqali rasm OCR — matn + til + ishonch."""

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
        return "vision.ocr"

    @property
    def description(self) -> str:
        return (
            "Rasm ustidan OCR (Gemini vision): matn, til, ishonch qaytaradi. "
            "Kirish — image_url YOKI image_bytes_base64 (bittasi)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "image_url": {
                    "type": "string",
                    "description": "Ochiq HTTP(S) rasm havolasi",
                },
                "image_bytes_base64": {
                    "type": "string",
                    "description": "Rasm baytlari base64 kodlangan (kamera snapshot chiqishi)",
                },
                "media_type": {
                    "type": "string",
                    "description": "MIME turi — default `image/jpeg` (image/png ham bo'lishi mumkin)",
                },
            },
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    @property
    def output_trust_level(self) -> TrustLevel:
        """OCR natijasi — tashqi manba (A-05)."""
        return TrustLevel.UNTRUSTED

    @property
    def idempotent(self) -> bool:
        return True

    @property
    def timeout_s(self) -> int:
        return 45

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=float(self.timeout_s))
        return self._client

    def _build_image_part(self, params: dict[str, Any]) -> dict[str, Any]:
        """Kirish parametrlaridan Gemini `parts` uchun rasm bloki quradi.

        Ikki manba (`image_url` va `image_bytes_base64`) bir vaqtda
        berilsa — bu noaniqlik, xato beramiz. Hech biri bo'lmasa ham
        xato (schema `required` bermaydi, chunki OR mantiqi — shuning
        uchun tekshiruv shu yerda).
        """
        image_url = str(params.get("image_url") or "").strip()
        image_b64 = str(params.get("image_bytes_base64") or "").strip()
        media_type = str(params.get("media_type") or "image/jpeg").strip() or "image/jpeg"

        if image_url and image_b64:
            msg = "vision.ocr: image_url va image_bytes_base64 birga berilmaydi (bittasi)"
            raise ToolError(msg)
        if not image_url and not image_b64:
            msg = "vision.ocr: image_url yoki image_bytes_base64 dan bittasi shart"
            raise ToolError(msg)

        if image_url:
            return {"file_data": {"file_uri": image_url, "mime_type": media_type}}

        # base64 validatsiyasi — chala satrni Gemini'ga jo'natsak ham
        # foyda yo'q, oldindan qo'l qisqartiramiz.
        try:
            _b64.b64decode(image_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            msg = f"vision.ocr: image_bytes_base64 noto'g'ri base64: {exc}"
            raise ToolError(msg) from exc
        return {"inline_data": {"mime_type": media_type, "data": image_b64}}

    async def _execute(self, params: dict[str, Any]) -> Any:
        if not self._api_key:
            msg = "vision.ocr: gemini_api_key sozlanmagan"
            raise ToolError(msg)

        image_part = self._build_image_part(params)
        payload = {
            "contents": [
                {
                    "parts": [
                        image_part,
                        {"text": "Rasmdagi matnni JSON tarzida qaytar."},
                    ]
                }
            ],
            "systemInstruction": {"parts": [{"text": _SYSTEM}]},
            "generationConfig": {
                "temperature": 0.1,
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
            msg = "Gemini kutilgan javob shaklini qaytarmadi (rasm ochilmagan bo'lishi mumkin)"
            raise ToolError(msg) from exc

        parsed = extract_json_object(text)
        if parsed is None:
            msg = "Gemini JSON obyekt qaytarmadi (dict emas yoki topilmadi)"
            raise ToolError(msg)

        # Model ba'zan kutilgan maydonni tashlab yuboradi — normallashtirish.
        ocr_text = str(parsed.get("text") or "")
        language = str(parsed.get("language") or "unknown")
        raw_conf: Any = parsed.get("confidence")
        confidence: float | None
        if raw_conf is None:
            confidence = None
        else:
            try:
                confidence = float(raw_conf)
            except (TypeError, ValueError):
                confidence = None

        log.info(
            "vision_ocr.done",
            text_len=len(ocr_text),
            language=language,
            has_confidence=confidence is not None,
        )
        return {
            "text": ocr_text,
            "language": language,
            "confidence": confidence,
        }

    async def aclose(self) -> None:
        """Ichki HTTP klientni yopadi (agar o'zi yaratgan bo'lsa)."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()


__all__ = [
    "DEFAULT_MODEL",
    "MAX_OUTPUT_TOKENS",
    "VisionOcrTool",
]
