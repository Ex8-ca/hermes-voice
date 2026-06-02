#!/usr/bin/env python3
"""
Faster Whisper STT Server — OpenAI-compatible API.

Exposes POST /v1/audio/transcriptions compatible with the OpenAI Whisper API
format. The voice web UI hits it at base_url=http://localhost:9001/v1.

Model stays loaded in GPU memory for instant transcription.
"""

import io
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("whisper-server")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# Model name. Options:
#   - "turbo" (default) → Systran/faster-whisper-large-v3-turbo (high accuracy)
#   - "Systran/faster-distil-whisper-large-v3" → 2x faster, slightly less accurate
#   - "tiny", "base", "small", "medium", "large-v3" → standard sizes
# Set via env: WHISPER_MODEL=Systran/faster-distil-whisper-large-v3
MODEL_NAME = os.getenv("WHISPER_MODEL", "turbo")
DEVICE = os.getenv("WHISPER_DEVICE", "auto")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float32")
HOST = os.getenv("WHISPER_HOST", "0.0.0.0")
PORT = int(os.getenv("WHISPER_PORT", "9001"))

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Faster Whisper STT Server", version="1.0.0")

# Global model — loaded once at startup
_model = None


def get_model():
    global _model
    if _model is None:
        logger.info("Loading faster-whisper model=%s device=%s compute=%s ...",
                     MODEL_NAME, DEVICE, COMPUTE_TYPE)
        from faster_whisper import WhisperModel
        _model = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)
        logger.info("Model loaded and ready.")
    return _model


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event():
    """Pre-load model so first request is fast."""
    get_model()


@app.get("/health")
async def health():
    return {"status": "healthy", "model": MODEL_NAME, "device": DEVICE}


@app.get("/v1/models")
async def list_models():
    """OpenAI-compatible model listing."""
    return {
        "object": "list",
        "data": [
            {
                "id": f"whisper-{MODEL_NAME}",
                "object": "model",
                "owned_by": "local",
            }
        ],
    }


@app.post("/v1/audio/transcriptions")
async def transcribe(
    file: UploadFile = File(...),
    model: str = Form("whisper-1"),
    language: Optional[str] = Form(None),
    prompt: Optional[str] = Form(None),
    response_format: Optional[str] = Form("json"),
    temperature: Optional[float] = Form(0.0),
):
    """OpenAI-compatible audio transcription endpoint.

    Accepts multipart form data with an audio file (mp3, wav, ogg, m4a, etc.)
    and returns the transcription text.
    """
    t0 = time.monotonic()

    # Read uploaded audio into a temp file (faster-whisper needs a path)
    audio_bytes = await file.read()
    suffix = Path(file.filename or "audio.ogg").suffix or ".ogg"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        model = get_model()

        kwargs = {
            "beam_size": 5,
            "vad_filter": True,
            "vad_parameters": {"min_silence_duration_ms": 500},
        }
        if language:
            kwargs["language"] = language
        if prompt:
            kwargs["initial_prompt"] = prompt
        if temperature is not None and temperature > 0:
            kwargs["temperature"] = temperature

        logger.info("Starting transcription of %s (%d bytes, suffix=%s)",
                     file.filename or "unknown", len(audio_bytes), suffix)

        segments, info = model.transcribe(tmp_path, **kwargs)
        transcript_parts = []
        for seg in segments:
            transcript_parts.append(seg.text)

        transcript = " ".join(transcript_parts).strip()
        elapsed = time.monotonic() - t0

        lang = getattr(info, "language", None) or "unknown"
        duration = getattr(info, "duration", 0.0) or 0.0

        logger.info(
            "Transcribed %.1fs audio in %.2fs (lang=%s, %d segments): %s",
            duration, elapsed, lang, len(transcript_parts),
            transcript[:80] + ("..." if len(transcript) > 80 else ""),
        )

        if response_format == "text":
            return JSONResponse(content=transcript or "", media_type="text/plain")

        return {
            "text": transcript,
            "language": lang,
            "duration": round(duration, 2),
            "segments": len(transcript_parts),
        }

    except Exception as e:
        elapsed = time.monotonic() - t0
        logger.exception("Transcription failed after %.2fs: %s", elapsed, e)
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(e), "type": "server_error"}},
        )

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("Starting Whisper STT server on %s:%d (model=%s)", HOST, PORT, MODEL_NAME)
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
