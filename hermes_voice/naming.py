"""
Assistant name resolution for hermes-voice.

Resolution order:
1. HERMES_NAME env var (single word, e.g. "Hermes")
2. ~/.hermes/name (a plain text file with just the name)
3. Default: "Hermes"

The name is used to personalize the voice system prompt
("You are {name}, a concise voice assistant…").
"""
import logging
import os
from pathlib import Path

logger = logging.getLogger("hermes-voice.naming")

_NAME_CACHE: str | None = None


def get_assistant_name() -> str:
    """Resolve the assistant's name using the configured fallback chain."""
    global _NAME_CACHE
    if _NAME_CACHE is not None:
        return _NAME_CACHE

    # 1. Env var override
    env_name = os.getenv("HERMES_NAME", "").strip()
    if env_name:
        _NAME_CACHE = env_name
        logger.info(f"Assistant name from HERMES_NAME env: {env_name}")
        return _NAME_CACHE

    # 2. ~/.hermes/name file
    name_file = Path.home() / ".hermes" / "name"
    if name_file.exists():
        file_name = name_file.read_text(encoding="utf-8").strip()
        if file_name:
            _NAME_CACHE = file_name
            logger.info(f"Assistant name from {name_file}: {file_name}")
            return _NAME_CACHE

    # 3. Default
    _NAME_CACHE = "Hermes"
    logger.info("Assistant name: using default 'Hermes'")
    return _NAME_CACHE


def clear_cache() -> None:
    """Clear the name cache (useful for tests)."""
    global _NAME_CACHE
    _NAME_CACHE = None
