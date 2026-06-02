# JARVIS Voice Shell — Production Dockerfile
# Multi-stage: shared base + CPU/GPU variants

# ── Base image (shared) ─────────────────────────────────────────────
FROM python:3.12-slim AS base

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    ffmpeg \
    libportaudio2 \
    libasound2 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cached layer)
COPY requirements.txt requirements-web.txt ./
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r requirements-web.txt

# Copy app
COPY . /app

# TTS cache directory
RUN mkdir -p /root/.cache/jarvis-voice-shell/tts_cache

EXPOSE 8989 9001

# Default command runs the web UI (assumes whisper-server runs separately)
CMD ["uvicorn", "web.jarvis_web:app", "--host", "0.0.0.0", "--port", "8989"]


# ── GPU variant ─────────────────────────────────────────────────────
FROM base AS gpu

# Install CUDA-enabled PyTorch (faster-whisper needs CUDA for GPU inference)
RUN pip install --no-cache-dir torch==2.3.0+cu121 torchvision==0.18.0+cu121 \
    --index-url https://download.pytorch.org/whl/cu121

# Note: requires nvidia-container-toolkit on host
# Run with: docker run --gpus all ...
