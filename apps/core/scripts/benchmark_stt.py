#!/usr/bin/env python3
"""`WhisperSTT` uchun HAQIQIY aniqlik benchmarki — TTS→STT round-trip orqali.

MUHIM CHEKLOV (yashirilmaydi): bu HAQIQIY INSON OVOZI EMAS. Bu skript
`MmsTTS` bilan matndan sun'iy audio yasaydi, keyin `WhisperSTT` bilan
o'sha audioni qayta matnga o'giradi va natijani asl matn bilan
solishtiradi. Bu — ikkita mustaqil model orqali "aylanma tekshiruv"
(sanity/regression signal), lekin HAQIQIY foydalanuvchi ovozidagi
talaffuz, urg'u, shovqin, mikrofon sifati kabi omillarni QAMRAB
OLMAYDI. Haqiqiy WER buni odatda YOMONLASHTIRADI (real, tabiiy nutq
har doim sun'iy TTS chiqishidan farq qiladi) — bu raqam "eng яхши holat"
taxmini, "kafolat" emas.

Ishlatish:

    uv run python scripts/benchmark_stt.py \\
        --whisper-model /path/to/whisper-uz-ct2 \\
        --mms-model /path/to/mms-tts-uz
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# 20 ta real ZET-uslubidagi buyruq — foydalanuvchining o'z misollariga
# ("hisobot chiqar", "yangi o'quvchi qo'sh", "bugungi to'lovlarni
# ko'rsat") mos, repo'dagi haqiqiy imkoniyatlar asosida (missiya,
# eslatma, hisobot, mijoz/o'quvchi, kalendar, Telegram).
COMMANDS = [
    "Hisobot chiqar",
    "Yangi o'quvchi qo'sh",
    "Bugungi to'lovlarni ko'rsat",
    "Ertaga soat o'nda uchrashuv qo'sh",
    "Oxirgi besh ta xabarni o'qi",
    "Yangi missiya boshla",
    "Bu haftalik sotuv hisobotini yubor",
    "Mijozlar ro'yxatini ko'rsat",
    "Eslatma qo'sh, ertaga qo'ng'iroq qilish",
    "Telegram kanaliga xabar yubor",
    "Bugungi kunlik pulsni ko'rsat",
    "Yangi vazifa qo'sh, hisobotni tekshirish",
    "O'quvchining balansini ko'rsat",
    "Kelgusi hafta uchun reja tuz",
    "Barcha faol missiyalarni ko'rsat",
    "Mahsulot qo'sh, narxi yuz ming so'm",
    "Bugun nechta buyurtma tushdi",
    "Xodimlar ro'yxatini yangila",
    "Oxirgi to'lovni bekor qil",
    "Ega profilini ko'rsat",
]


def _word_error_rate(reference: str, hypothesis: str) -> tuple[float, int, int]:
    """Klassik WER — so'z darajasidagi Levenshtein masofasi / mos so'zlar soni.

    Qaytaradi: (WER foizi, tahrirlar soni, mos so'zlar soni).

    Har bir so'zdagi TINISH BELGILARI (nuqta, vergul) OLIB TASHLANADI
    solishtirishdan oldin — Whisper tabiiy jumla oxiriga nuqta qo'shishi
    mumkin ("ko'rsat" → "ko'rsat."), bu buyruq-tanish tizimi uchun
    XATO EMAS (chaqiruvchi kod baribir normalizatsiya qiladi), lekin
    xom WER'ni sun'iy oshiradi.
    """
    import string

    def _strip_punct(word: str) -> str:
        return word.strip(string.punctuation)

    ref = [w for w in (_strip_punct(w) for w in reference.lower().split()) if w]
    hyp = [w for w in (_strip_punct(w) for w in hypothesis.lower().split()) if w]
    n, m = len(ref), len(hyp)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    edits = dp[n][m]
    wer = (edits / n * 100) if n else (0.0 if not m else 100.0)
    return wer, edits, n


async def main() -> int:
    parser = argparse.ArgumentParser(description="WhisperSTT TTS-round-trip benchmark")
    parser.add_argument("--whisper-model", required=True)
    parser.add_argument("--mms-model", required=True)
    args = parser.parse_args()

    from zet.voice.mms_tts import MmsTTS
    from zet.voice.whisper_stt import WhisperSTT

    tts = MmsTTS(model_path=args.mms_model)
    stt = WhisperSTT(model_path=args.whisper_model)

    print(f"{'#':>3}  {'Kutilgan':<45} {'Olingan':<45} {'WER':>7}  {'lat(s)':>7}")
    print("-" * 112)

    total_edits = 0
    total_words = 0
    total_latency = 0.0
    per_command_wer: list[float] = []

    for i, command in enumerate(COMMANDS, 1):
        t0 = time.monotonic()
        audio = await tts.synthesize(command)
        result = await stt.transcribe(audio.audio_data, audio_format="ogg", language="uz")
        latency = time.monotonic() - t0
        total_latency += latency

        wer, edits, n_words = _word_error_rate(command, result.text)
        total_edits += edits
        total_words += n_words
        per_command_wer.append(wer)

        print(f"{i:>3}  {command:<45} {result.text:<45} {wer:>6.1f}%  {latency:>6.2f}")

    overall_wer = (total_edits / total_words * 100) if total_words else 0.0
    avg_latency = total_latency / len(COMMANDS)

    print("-" * 112)
    print(f"UMUMIY WER (barcha so'zlar bo'yicha):     {overall_wer:.2f}%")
    print(
        f"O'rtacha buyruq-boshiga WER:                {sum(per_command_wer) / len(per_command_wer):.2f}%"
    )
    print(
        f"To'liq to'g'ri (WER=0%) buyruqlar:          {sum(1 for w in per_command_wer if w == 0)}/{len(COMMANDS)}"
    )
    print(f"O'rtacha latency (TTS+STT, buyruq boshiga): {avg_latency:.2f}s")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
