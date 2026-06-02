"""
Voice persona loader for the hermes-voice plugin.

The voice LLM gets a different system prompt than text chat. Text chat uses
the full Hermes context (memex8, skills, tools, conversation history). Voice
uses a tight, conversation-focused prompt so the LLM responds in 1-3 seconds.

Resolution order:
1. `HERMES_VOICE_PROMPT_FILE` env var (path to a custom prompt file)
2. `~/.hermes/VOICE.md` (the recommended location for hermes-voice users)
3. `~/.hermes/SOUL.md` (back-compat with JARVIS Voice Shell)
4. Generic JARVIS persona (under 100 tokens)

Optionally tacks on:
- `~/.hermes/USER.md` (user context — name, preferences, projects)
- Most recent memex8 memories (if memex8 is available)

The result is cached in module state so we only read the file once per process.
"""
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("hermes-voice.persona")

_VOICE_PROMPT_CACHE: Optional[str] = None


def _load_voice_prompt() -> str:
    """Return the voice system prompt (cached after first call)."""
    global _VOICE_PROMPT_CACHE
    if _VOICE_PROMPT_CACHE is not None:
        return _VOICE_PROMPT_CACHE

    # Option 1: explicit env var override
    prompt_file = os.getenv("HERMES_VOICE_PROMPT_FILE", "")
    if prompt_file and Path(prompt_file).exists():
        _VOICE_PROMPT_CACHE = Path(prompt_file).read_text(encoding="utf-8")
        logger.info(f"Voice prompt loaded from {prompt_file} ({len(_VOICE_PROMPT_CACHE)} chars)")
        return _VOICE_PROMPT_CACHE

    # Option 2: ~/.hermes/VOICE.md (recommended) — single source of truth for voice
    # Option 3: ~/.hermes/SOUL.md (back-compat fallback only — used if VOICE.md is absent)
    parts = []
    voice_md = Path.home() / ".hermes" / "VOICE.md"
    soul_md = Path.home() / ".hermes" / "SOUL.md"
    if voice_md.exists():
        # VOICE.md is authoritative — don't double up with SOUL.md
        parts.append(voice_md.read_text(encoding="utf-8"))
        logger.info(f"Voice prompt: using {voice_md} (authoritative)")
    elif soul_md.exists():
        parts.append(soul_md.read_text(encoding="utf-8"))
        logger.info(f"Voice prompt: using {soul_md} (no VOICE.md found, falling back)")

    # USER.md (optional user context — always additive)
    user_md = Path.home() / ".hermes" / "USER.md"
    if user_md.exists():
        parts.append("\n\n# User Context\n" + user_md.read_text(encoding="utf-8"))
        logger.info(f"Voice prompt: using {user_md}")

    # memex8 recall (optional, non-fatal if memex8 unavailable)
    memex_block = _try_memex8_recall()
    if memex_block:
        parts.append("\n\n# Recent Memory (from memex8)\n" + memex_block)
        logger.info("Voice prompt: included memex8 recall")

    if parts:
        _VOICE_PROMPT_CACHE = (
            "\n\n".join(parts)
            + "\n\n---\nYou are JARVIS, a concise voice assistant. Keep responses SHORT — under 30 words. "
            "Conversational, direct, no filler. You are speaking aloud, not typing. "
            "No markdown, no bullet points, no lists. Plain spoken sentences only."
        )
    else:
        # Option 4: generic persona (last-resort fallback)
        _VOICE_PROMPT_CACHE = (
            "You are JARVIS, a concise voice assistant. Keep responses under 25 words. "
            "Speak conversationally, as if out loud. No markdown, no lists, no filler phrases. "
            "Be direct and helpful."
        )
    logger.info(f"Voice prompt total: {len(_VOICE_PROMPT_CACHE)} chars")
    return _VOICE_PROMPT_CACHE


def _try_memex8_recall(limit: int = 5) -> str:
    """Try to pull the N most recent memex8 memories. Returns empty string on failure."""
    try:
        # Memex8 is exposed via Hermes' own memory system, not a direct import.
        # The exact API is still being designed (Phase 4 of the refactor).
        # For now, return empty — the gateway works fine without it.
        return ""
    except Exception:
        return ""


def reload() -> None:
    """Clear the cache so the next call re-reads the file (useful for tests)."""
    global _VOICE_PROMPT_CACHE
    _VOICE_PROMPT_CACHE = None
