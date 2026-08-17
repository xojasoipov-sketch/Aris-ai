"""NavoiyTTS — Hetzner GPU serverida ishlaydigan Navoiy TTS mijozi (client).

NEGA ALOHIDA SERVIS. `aisha-org/navoiy-tts` (CosyVoice2-0.5B asosida)
GPU'siz amaliy tezlikda ishlamaydi — ZET backend'ining o'zi (Railway/
Hetzner CPU konteyneri) buni to'g'ridan-to'g'ri yuklay olmaydi. Shuning
uchun bu klass MODELNI O'ZI ISHGA TUSHIRMAYDI — u alohida, GPU'li
Hetzner serverida ishlaydigan mustaqil inference mikroservisga ("Navoiy
TTS server", `infra/hetzner/navoiy-tts-service/`) HTTP orqali murojaat
qiladigan yupqa mijoz, xuddi `AzureTTS`/`ElevenLabsTTS` tashqi API'ga
murojaat qilgani kabi (farqi — bu "tashqi API" o'zimizning serverimiz).

MUHIM, OCHIQ E'LON QILINGAN CHEKLOVLAR:
    - GPU serveri ALOHIDA joylashtirilishi va ishga tushirilishi kerak
      (`infra/hetzner/navoiy-tts-service/README.md`ga qarang) — bu
      klassning o'zi hech qanday modelni yuklamaydi, faqat mavjud
      xizmatga ulanadi.
    - Ismlar, o'zlashma so'zlar, kam uchraydigan raqam formatlarini
      Navoiy TTS noto'g'ri talaffuz qilishi mumkin (aisha-org hujjatlari
      bo'yicha) — bu klass darajasida HAL QILINMAGAN, faqat
      `text_normalize.normalize_for_tts()` orqali eng keng tarqalgan
      holatlar (raqam/sana/vaqt) oldindan yumshatiladi.
    - Dialekt va aralash til (o'zbek+rus/ingliz) TO'LIQ SINALMAGAN.

Matn UZUNLIGI: `MAX_CHARS_PER_REQUEST`dan uzun matn avtomatik jumla
chegaralarida bo'laklarga bo'linadi, har bo'lak alohida so'raladi va
audio baytlari KETMA-KET BIRLASHTIRILADI (Opus/OGG oqimlarni ketma-ket
ulash — standart, ko'p pleyerlar to'g'ri o'ynatadi; agar kelajakda
muammo chiqsa, `av` orqali qayta multiplekslash kerak bo'lishi mumkin —
BILINGAN, hozircha sinovdan o'tkazilmagan yo'l).

Fail-open: `base_url` yo'q yoki xizmat javob bermasa (`RuntimeError`) —
chaqiruvchi (`get_tts()`) navbatdagi provayderga (`MmsTTS` → Azure →
ElevenLabs → Stub) o'tadi — boshqa "real-vs-stub" naqshlar bilan bir xil.

Bog'liq qarorlar:
    V-18 — ovoz birinchi darajali
    ADR-0007 — lokal birinchi
"""

from __future__ import annotations

import re

import httpx
import structlog

from zet.voice.text_normalize import normalize_for_tts
from zet.voice.tts import TTSProvider, TTSResult

log = structlog.get_logger(__name__)

MAX_CHARS_PER_REQUEST = 2000
"""Bitta so'rovda yuboriladigan matn chegarasi.

CosyVoice2-asosidagi modellar juda uzun matnda sifat pasayishi/xotira
muammosi ko'rsatishi mumkin (umumiy VITS/diffusion-asosli TTS'lar
naqshi) — aniq raqam `aisha-org/navoiy-tts` uchun hujjatlashtirilmagan,
shuning uchun ehtiyotkorlik bilan ~2000 belgi (taxminan 1-2 daqiqalik
nutq) tanlandi. Bundan uzun matn bo'laklarga bo'linadi."""

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")


def chunk_text(text: str, *, max_chars: int = MAX_CHARS_PER_REQUEST) -> list[str]:
    """Matnni jumla chegaralarida `max_chars`dan oshmaydigan bo'laklarga bo'ladi.

    Sof funksiya — TTS'siz mustaqil test qilinadi. Jumla juda uzun
    bo'lsa (yagona jumla `max_chars`dan katta) — so'z chegarasida
    majburan bo'linadi (matn hech qachon kesilib qolmaydi).
    """
    if not text.strip():
        return []
    if len(text) <= max_chars:
        return [text]

    sentences = _SENTENCE_BOUNDARY_RE.split(text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(sentence) <= max_chars:
            current = sentence
        else:
            # Yagona jumlaning o'zi juda uzun — so'z chegarasida bo'lamiz.
            words = sentence.split()
            piece = ""
            for word in words:
                candidate_piece = f"{piece} {word}".strip() if piece else word
                if len(candidate_piece) <= max_chars:
                    piece = candidate_piece
                else:
                    if piece:
                        chunks.append(piece)
                    piece = word
            current = piece
    if current:
        chunks.append(current)
    return chunks


class NavoiyTTS(TTSProvider):
    """Hetzner GPU serverida ishlaydigan Navoiy TTS (CosyVoice2) mijozi."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/") if base_url else None
        self._client = client
        self._owns_client = client is None
        self._timeout_s = timeout_s

    @property
    def is_configured(self) -> bool:
        """Manzil berilganmi — chaqiruvchi haqiqiy Navoiy TTS tanlashi mumkinmi.

        DIQQAT: bu xizmat HAQIQATAN ishga tushirilgan/erishilishi mumkinmi
        deb TEKSHIRMAYDI (masalan `ping`) — faqat konfiguratsiya
        borligini bildiradi. Haqiqiy erishuvchanlik `synthesize()`
        chaqirilganda tekshiriladi va xato bo'lsa `RuntimeError`
        tarqatiladi, chaqiruvchi keyingi provayderga o'tadi.
        """
        return bool(self._base_url)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_s)
        return self._client

    async def _synthesize_chunk(self, text: str) -> bytes:
        try:
            response = await self._get_client().post(
                f"{self._base_url}/synthesize",
                json={"text": text},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            log.warning("navoiy_tts.http_error", status=exc.response.status_code)
            raise RuntimeError(f"NavoiyTTS xatosi: HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            log.warning("navoiy_tts.network_error", error=str(exc))
            raise RuntimeError(f"NavoiyTTS tarmoq xatosi: {exc}") from exc
        return response.content

    async def synthesize(self, text: str, *, language: str = "uz") -> TTSResult:  # noqa: ARG002
        """Matndan OGG/Opus audio — Hetzner GPU serveridagi Navoiy TTS orqali.

        Matn avval `normalize_for_tts()` bilan tozalanadi (raqam/sana/
        vaqt/skript), keyin kerak bo'lsa `chunk_text()` bilan bo'laklarga
        bo'linadi va HAR BO'LAK ALOHIDA SO'RALADI — natijalar ketma-ket
        birlashtiriladi.
        """
        if not self._base_url:
            raise RuntimeError("NavoiyTTS: manzil yo'q — ZET_NAVOIY_TTS_BASE_URL sozlanmagan")

        normalized = normalize_for_tts(text)
        chunks = chunk_text(normalized)
        if not chunks:
            return TTSResult(audio_data=b"", audio_format="ogg", duration_s=0.0, text=text)

        audio_parts = [await self._synthesize_chunk(chunk) for chunk in chunks]
        audio_bytes = b"".join(audio_parts)

        log.info(
            "navoiy_tts.synthesized",
            text_length=len(text),
            chunk_count=len(chunks),
            audio_size=len(audio_bytes),
        )
        return TTSResult(audio_data=audio_bytes, audio_format="ogg", duration_s=0.0, text=text)

    async def aclose(self) -> None:
        """Ichki HTTP klientni yopadi (agar o'zi yaratgan bo'lsa)."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()


__all__ = ["MAX_CHARS_PER_REQUEST", "NavoiyTTS", "chunk_text"]
