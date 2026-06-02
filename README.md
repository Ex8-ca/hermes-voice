# JARVIS Voice Shell

Real-time voice pipeline for AI assistants. Streaming STT, streaming LLM, streaming TTS, with filler phrases that mask latency. Works in two modes: single-machine (mic + STT + LLM + TTS on one box) and split (mic on one machine, STT/LLM/TTS on another).

> JARVIS is used here as an assistant-style project name. This project is not affiliated with Marvel, Disney, OpenAI, Microsoft, or Nous Research.

## Highlights

- **Always-on VAD** — energy-based voice activity detection, ~315ms end-silence for natural turn-taking
- **Barge-in** — interrupt the AI mid-response by speaking over it (sidetone cancellation removes the AI's own audio)
- **Streaming LLM** — Groq (~150ms first token), DeepSeek, OpenAI, or local (Ollama/vLLM)
- **Filler phrases** — "One sec..." or "Checking..." plays immediately to mask LLM latency
- **TTS streaming** — Edge TTS audio chunks stream to the client as they synthesize
- **Two deployment modes** — single-machine (web UI) or split (Python client → gateway)
- **Multi-provider** — auto-pick first available LLM from `.env`
- **Docker** — one-command deployment with GPU support

## Two modes

### Single-machine (most users)

Mic, STT, LLM, TTS all on one computer. Just open the web UI.

```
Microphone → Browser → Web UI (port 8989) → Whisper (port 9001) → LLM (Groq/DeepSeek) → TTS → Speakers
```

### Split architecture (mic on one box, server on another)

Useful when you want the mic near you but heavy compute (Whisper, LLM) on a server.

```
Client machine                           Server machine
─────────────                            ──────────────
Microphone → Python client ──WS─►  JARVIS Gateway ──► Whisper ──► LLM ──► TTS ──► WebSocket
                ▲                                              │
                └────────── TTS audio back ─────────────────────┘
Speakers
```

## Quickstart (single-machine, Docker)

```bash
git clone https://github.com/Ex8-ca/jarvis-voice-shell.git
cd jarvis-voice-shell

cp .env.example .env
# Edit .env and set GROQ_API_KEY=*** (or DEEPSEEK_API_KEY / OPENAI_API_KEY)

docker compose up -d
open http://localhost:8989
```

For GPU acceleration: `docker compose build --build-arg TARGET=gpu` (requires `nvidia-container-toolkit`).

## Quickstart (single-machine, manual)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements-web.txt
pip install -r requirements-whisper.txt

cp .env.example .env
# Edit .env with your LLM key

# Terminal 1: Whisper STT
python whisper-server/server.py &

# Terminal 2: Web UI
uvicorn web.jarvis_web:app --host 0.0.0.0 --port 8989

open http://localhost:8989
```

## Quickstart (split architecture)

### On the server (where Whisper + LLM + TTS run)

```bash
pip install -r requirements-web.txt -r requirements-whisper.txt
cp .env.example .env
# Set your LLM key

python whisper-server/server.py &
uvicorn web.jarvis_web:app --host 0.0.0.0 --port 8989
```

The web UI on port 8989 hosts the gateway WebSocket. Clients connect to it.

### On the client machine (where the mic is)

```bash
git clone https://github.com/Ex8-ca/jarvis-voice-shell.git
cd jarvis-voice-shell
pip install -r requirements-client.txt

# Point at the server
export JARVIS_WS_HOST=192.168.1.50
export JARVIS_WS_PORT=8989

python jarvis_voice_client.py
```

Or run as a systemd service (Linux) — see `systemd/jarvis-voice-client.service` for an example.

**Barge-in (interrupting the AI):** when the AI is speaking and you start talking, the client
performs sidetone cancellation (subtracts the AI's TTS audio from the mic input) and detects your
voice. It sends a `barge_in` message to the gateway which cancels the in-flight LLM/TTS task.

Tune via env vars (see `.env.example`):
- `JARVIS_SIDETONE_DELAY_MS` — alignment between TTS output and mic input (default 80ms)
- `JARVIS_BARGE_IN_RMS` — minimum voice energy to interrupt (default 800)

## LLM provider priority

The gateway picks the first LLM with a key set in `.env`:

1. **Groq** (`GROQ_API_KEY=***`) — fastest, free tier, ~150ms first token
2. **DeepSeek** (`DEEPSEEK_API_KEY=***`) — high quality, ~500ms first token
3. **OpenAI** (`OPENAI_API_KEY=***`) — reliable, expensive
4. **Local** (`LOCAL_LLM_URL=http://...`) — Ollama/vLLM/LM Studio, $0
5. **Hermes** (`HERMES_URL=http://...`) — any OpenAI-compatible proxy

For most users, Groq with `llama-3.1-8b-instant` is the sweet spot. Free, fast, good enough for voice.

## Latency budget

Typical end-to-end (you-stop-talking → first response audio byte):

| Component | Time |
|-----------|------|
| VAD end-silence | 315ms |
| Whisper STT | ~400ms |
| Filler phrase playback | ~600ms (overlaps with LLM) |
| LLM first token (Groq) | ~150ms |
| LLM full response | ~800ms |
| TTS first chunk | ~400ms |
| **Perceived latency** | **~1.0s** (filler masks LLM) |

## Configuration

See `.env.example` for the full list. Most important:

```bash
# LLM (one of these)
GROQ_API_KEY=***

# Voice persona (optional)
# JARVIS_SYSTEM_PROMPT_FILE=/path/to/your/voice-prompt.txt

# Filler phrases (set empty to disable)
JARVIS_FILLER_PHRASES=One sec...,Checking...,On it...

# Whisper model: "turbo" (default) or "Systran/faster-distil-whisper-large-v3" (faster)
WHISPER_MODEL=turbo
```

## Files

- `web/jarvis_web.py` — FastAPI web UI (single-machine mode) and gateway (split mode)
- `jarvis_voice_client.py` — Python client for split-architecture mode
- `whisper-server/server.py` — Faster-Whisper STT server
- `Dockerfile` + `docker-compose.yml` — Production deployment
- `systemd/jarvis-voice-client.service` — Example systemd unit for the client

## CLI mode (push-to-talk)

For terminal-based push-to-talk:

```bash
pip install -e .
jarvis-voice run --input-mode ptt --brain http
```

See `python -m jarvis_voice_shell.cli --help` for all options.

## Development

```bash
python -m pytest
python -m ruff check .
```

## License

MIT
