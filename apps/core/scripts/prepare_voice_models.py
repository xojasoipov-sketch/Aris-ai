#!/usr/bin/env python3
"""Lokal ovoz (STT/TTS) modellarini bir martalik tayyorlaydi (ADR-0007).

NEGA. `WhisperSTT` (`zet/voice/whisper_stt.py`) va `MmsTTS`
(`zet/voice/mms_tts.py`) ishlashi uchun model og'irliklari diskda
bo'lishi kerak. Bu skript ULARNI RUNTIME'DA EMAS, BIR MARTA (deploy'dan
oldin yoki keyin, operator tomonidan qo'lda) tayyorlaydi:

    STT: `islomov/rubaistt_v2_medium` (HuggingFace Transformers Whisper
         checkpoint, Apache-2.0) → CTranslate2 int8 formatiga convert
         qilinadi (`faster_whisper`/`ctranslate2` shu formatni kutadi).
    TTS: `facebook/mms-tts-uzb-script_cyrillic` (VITS, CC-BY-NC-4.0 —
         FAQAT NOTIJORAT, `zet/voice/mms_tts.py` docstring'iga qarang)
         HuggingFace'dan to'g'ridan-to'g'ri katalogga yuklab olinadi.

Natija katalog yo'llari `zet.config.Settings.whisper_model_path` /
`.mms_tts_model_path` default qiymatlariga MOS keladi
(`/data/voice-models/...`) — production'da bu doimiy Docker hajmga
yoziladi (Postgres/vault volume'lari bilan bir xil naqsh, `Dockerfile`
izohiga qarang), shuning uchun bir marta ishga tushirilsa har
redeploy'da qayta yuklash shart emas.

Ishlatish:

    # Ikkalasi ham, default yo'llarga (/data/voice-models/...)
    uv run python scripts/prepare_voice_models.py

    # Faqat bittasi, boshqa katalogga
    uv run python scripts/prepare_voice_models.py --only stt \\
        --whisper-out ./models/whisper-uz-ct2

Qayta ishga tushirish xavfsiz: `--force` berilmasa, katalog allaqachon
mavjud va bo'sh bo'lmasa — o'tkazib yuboriladi (qayta yuklab
olinmaydi).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_DEFAULT_WHISPER_SOURCE = "islomov/rubaistt_v2_medium"
_DEFAULT_WHISPER_OUT = "/data/voice-models/whisper-uz-ct2"
_DEFAULT_MMS_SOURCE = "facebook/mms-tts-uzb-script_cyrillic"
_DEFAULT_MMS_OUT = "/data/voice-models/mms-tts-uz"


def _dir_has_files(path: Path) -> bool:
    return path.is_dir() and any(path.iterdir())


def prepare_whisper(*, source: str, output_dir: str, quantization: str, force: bool) -> bool:
    """`source`ni CTranslate2 int8 formatiga convert qilib `output_dir`ga yozadi."""
    out = Path(output_dir)
    if not force and _dir_has_files(out):
        print(f"[stt] {output_dir} allaqachon mavjud — o'tkazib yuborildi (--force bilan qayta)")
        return True

    print(f"[stt] {source} → {output_dir} (CTranslate2, {quantization}) — yuklanmoqda...")
    try:
        from ctranslate2.converters import TransformersConverter
    except ImportError as exc:
        print(f"[stt] XATO: ctranslate2 o'rnatilmagan: {exc}", file=sys.stderr)
        return False

    try:
        converter = TransformersConverter(source)
        converter.convert(output_dir, quantization=quantization, force=force)
    except Exception as exc:
        print(f"[stt] XATO: convert muvaffaqiyatsiz: {exc}", file=sys.stderr)
        return False

    print(f"[stt] TAYYOR — {output_dir}")
    return True


def prepare_mms_tts(*, source: str, output_dir: str, force: bool) -> bool:
    """`source` HuggingFace repo'sini `output_dir`ga to'liq yuklab oladi."""
    out = Path(output_dir)
    if not force and _dir_has_files(out):
        print(f"[tts] {output_dir} allaqachon mavjud — o'tkazib yuborildi (--force bilan qayta)")
        return True

    print(f"[tts] {source} → {output_dir} — yuklanmoqda...")
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        print(f"[tts] XATO: huggingface_hub o'rnatilmagan: {exc}", file=sys.stderr)
        return False

    try:
        out.mkdir(parents=True, exist_ok=True)
        snapshot_download(repo_id=source, local_dir=str(out))
    except Exception as exc:
        print(f"[tts] XATO: yuklab olish muvaffaqiyatsiz: {exc}", file=sys.stderr)
        return False

    print(f"[tts] TAYYOR — {output_dir}")
    print(
        "[tts] ESLATMA: bu model CC-BY-NC-4.0 (faqat notijorat) — "
        "zet/voice/mms_tts.py docstring'idagi litsenziya ogohlantirishiga qarang."
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--only",
        choices=["stt", "tts", "both"],
        default="both",
        help="Faqat bitta modelni tayyorlash (default: ikkalasi ham)",
    )
    parser.add_argument("--whisper-source", default=_DEFAULT_WHISPER_SOURCE)
    parser.add_argument("--whisper-out", default=_DEFAULT_WHISPER_OUT)
    parser.add_argument(
        "--quantization",
        default="int8",
        help="CTranslate2 kvantlash turi (default: int8 — CPU uchun eng yengil)",
    )
    parser.add_argument("--mms-source", default=_DEFAULT_MMS_SOURCE)
    parser.add_argument("--mms-out", default=_DEFAULT_MMS_OUT)
    parser.add_argument(
        "--force", action="store_true", help="Katalog mavjud bo'lsa ham qayta yuklash"
    )
    args = parser.parse_args()

    ok = True
    if args.only in ("stt", "both"):
        ok = (
            prepare_whisper(
                source=args.whisper_source,
                output_dir=args.whisper_out,
                quantization=args.quantization,
                force=args.force,
            )
            and ok
        )
    if args.only in ("tts", "both"):
        ok = (
            prepare_mms_tts(source=args.mms_source, output_dir=args.mms_out, force=args.force)
            and ok
        )

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
