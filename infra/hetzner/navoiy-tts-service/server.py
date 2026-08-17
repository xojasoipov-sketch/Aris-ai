"""Navoiy TTS (CosyVoice2) inference mikroservisi — GPU serverida ishlaydi.

TO'LIQ SINALMAGAN — README.md dagi "OCHIQ E'LON QILINGAN HOLAT"
bo'limiga qarang. Bu server `aisha-org/navoiy-tts/inference.py`ni
subprocess sifatida chaqiradi (Python API'ni to'g'ridan-to'g'ri
integratsiya qilish o'rniga — sabab README.md'da), natija WAV faylni
o'qib OGG/Opus'ga kodlaydi (`zet/voice/mms_tts.py`dagi bilan bir xil,
sinovdan o'tgan PyAV texnikasi — bu yerda mustaqil nusxa, chunki bu
konteyner alohida, GPU-maxsus Python muhitida ishlaydi va asosiy `zet`
paketiga bog'liq emas).

Kontrakt: `POST /synthesize {"text": "..."}` → `audio/ogg` baytlar
(Telegram `sendVoice`ga to'g'ridan-to'g'ri mos, 24 kHz Opus).
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

log = logging.getLogger("navoiy_tts_service")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Navoiy TTS inference service")

# Barcha yo'llar/parametrlar env orqali — README.md 3-qadamiga qarang
# (haqiqiy reference/emotion qiymatlarini SIZ tasdiqlashingiz kerak).
COSYVOICE_DIR = os.environ.get("COSYVOICE_DIR", "/opt/CosyVoice")
BASE_MODEL_DIR = os.environ.get("BASE_MODEL_DIR", "/opt/CosyVoice/pretrained_models/CosyVoice2-0.5B")
CHECKPOINT_PATH = os.environ.get("CHECKPOINT_PATH", "/opt/navoiy-tts/emotion_600h_joint.pt")
INFERENCE_SCRIPT = os.environ.get("INFERENCE_SCRIPT", "/opt/navoiy-tts/inference.py")
REFERENCE_PATH = os.environ.get("NAVOIY_REFERENCE_PATH", "")
DEFAULT_EMOTION = os.environ.get("NAVOIY_DEFAULT_EMOTION", "neutral")
SAMPLE_RATE = 24000  # aisha-org hujjatlariga ko'ra — README.md manbalariga qarang
SYNTHESIS_TIMEOUT_S = float(os.environ.get("NAVOIY_TIMEOUT_S", "120"))


class SynthesizeRequest(BaseModel):
    text: str
    emotion: str | None = None


def _wav_to_ogg_opus(wav_path: Path) -> bytes:
    """WAV faylni o'qib OGG/Opus baytlariga kodlaydi (24 kHz — Opus tabiiy chastotasi)."""
    import av
    import numpy as np

    with av.open(str(wav_path), mode="r") as decoder:
        stream = decoder.streams.audio[0]
        frames = list(decoder.decode(stream))
        if not frames:
            raise RuntimeError("WAV fayl bo'sh yoki dekodlab bo'lmadi")
        samples = np.concatenate([f.to_ndarray().flatten() for f in frames]).astype(np.float32)
        # Agar WAV int16 bo'lsa, to_ndarray() int16 qaytarishi mumkin — [-1, 1]ga normallashtiramiz.
        if samples.dtype != np.float32 or np.abs(samples).max() > 1.0:
            samples = samples.astype(np.float32) / 32768.0

    buffer = io.BytesIO()
    with av.open(buffer, mode="w", format="ogg") as container:
        out_stream = container.add_stream("libopus", rate=SAMPLE_RATE)
        out_stream.layout = "mono"
        frame = av.AudioFrame.from_ndarray(
            np.ascontiguousarray(samples.reshape(1, -1)), format="flt", layout="mono"
        )
        frame.sample_rate = SAMPLE_RATE
        for packet in out_stream.encode(frame):
            container.mux(packet)
        for packet in out_stream.encode(None):
            container.mux(packet)
    return buffer.getvalue()


async def _run_inference(text: str, emotion: str) -> Path:
    """`navoiy-tts/inference.py`ni subprocess sifatida chaqiradi, chiqish WAV yo'lini qaytaradi."""
    if not REFERENCE_PATH:
        raise RuntimeError(
            "NAVOIY_REFERENCE_PATH sozlanmagan — README.md 3-qadamiga qarang: "
            "/opt/navoiy-tts ichidagi haqiqiy reference audio faylini toping va shu env'ga yozing."
        )

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        output_path = Path(tmp.name)

    cmd = [
        "python",
        INFERENCE_SCRIPT,
        "--cosyvoice-dir",
        COSYVOICE_DIR,
        "--base-model-dir",
        BASE_MODEL_DIR,
        "--checkpoint",
        CHECKPOINT_PATH,
        "--reference",
        REFERENCE_PATH,
        "--text",
        text,
        "--emotion",
        emotion,
        "--output",
        str(output_path),
    ]
    log.info("inference_start: text_length=%d emotion=%s", len(text), emotion)
    t0 = time.monotonic()

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=SYNTHESIS_TIMEOUT_S)
    except TimeoutError:
        proc.kill()
        raise RuntimeError(f"inference.py {SYNTHESIS_TIMEOUT_S}s ichida tugamadi (timeout)") from None

    latency = time.monotonic() - t0
    if proc.returncode != 0:
        log.error("inference_failed: stderr=%s", stderr.decode(errors="replace")[:2000])
        raise RuntimeError(f"inference.py xato bilan chiqdi (kod {proc.returncode}): "
                            f"{stderr.decode(errors='replace')[:500]}")

    log.info("inference_done: latency_s=%.2f", latency)
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("inference.py muvaffaqiyatli chiqdi, lekin chiqish fayli bo'sh/yo'q")
    return output_path


@app.get("/health")
async def health() -> dict[str, bool | str]:
    return {
        "ok": True,
        "reference_configured": bool(REFERENCE_PATH),
        "checkpoint_exists": Path(CHECKPOINT_PATH).exists(),
    }


@app.post("/synthesize")
async def synthesize(req: SynthesizeRequest) -> Response:
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text bo'sh bo'lishi mumkin emas")

    emotion = req.emotion or DEFAULT_EMOTION
    output_path: Path | None = None
    try:
        output_path = await _run_inference(req.text, emotion)
        audio_bytes = _wav_to_ogg_opus(output_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        if output_path is not None and output_path.exists():
            output_path.unlink(missing_ok=True)

    return Response(content=audio_bytes, media_type="audio/ogg")
