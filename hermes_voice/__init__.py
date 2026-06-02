"""
hermes-voice: a Hermes plugin for low-latency voice AI.

Components:
- gateway.py — FastAPI WebSocket server (browser UI + Python client)
- client.py — desktop mic/speaker (talks to the gateway over WebSocket)
- vad.py — energy-based voice activity detection
- llm.py — multi-provider LLM dispatcher (Groq, DeepSeek, OpenAI, local, Hermes)
- stt.py — local Whisper HTTP client
- tts.py — Edge TTS streaming (Piper swappable)
- persona.py — loads VOICE.md + USER.md
- memory.py — voice_memory.md persistent conversation log
- tools/ — pluggable tool dispatcher (memex8, web, etc.)

Run from the plugin directory:
    cd ~/.hermes/plugins/hermes-voice
    uvicorn gateway:app --host 0.0.0.0 --port 8989

Or use the bundled launcher: ./run.sh
"""

__version__ = "0.1.0"
__plugin_name__ = "hermes-voice"
