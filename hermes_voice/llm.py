"""
Multi-provider LLM dispatcher for the hermes-voice plugin.

Provider priority: Groq → DeepSeek → OpenAI → Local → Hermes
The first provider with a configured key wins.

All providers speak OpenAI-compatible /v1/chat/completions, so the call shape
is identical — only URL, key, and model change.

Voice-specific notes:
- Streaming is mandatory (we want first-token latency < 500ms)
- Temperature is fixed at 0.7 for natural conversation
- Max tokens is capped to keep responses under 60 words (voice-friendly)
- No tools passed in the request body — tools are handled by the gateway's
  text-based [[TOOL:...]] parser after the LLM responds.
"""
import json
import logging
import os
from typing import AsyncIterator, Optional, Tuple

import httpx

logger = logging.getLogger("hermes-voice.llm")

# ── Provider configuration (env-driven) ──────────────────────────────

# Groq — fastest, has free tier, ~150ms first token
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_URL = os.getenv("GROQ_URL", "https://api.groq.com/openai/v1/chat/completions")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

# DeepSeek — high quality, pay-per-token, ~500ms first token
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL = os.getenv("DEEPSEEK_URL", "https://api.deepseek.com/v1/chat/completions")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# OpenAI — reliable, expensive, ~600ms first token
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_URL = os.getenv("OPENAI_URL", "https://api.openai.com/v1/chat/completions")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Local (Ollama, vLLM, LM Studio — OpenAI-compatible)
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:7b")
LOCAL_LLM_KEY = os.getenv("LOCAL_LLM_KEY", "not-needed")

# Hermes Agent or any other OpenAI-compatible local proxy
HERMES_URL = os.getenv("HERMES_URL", "http://127.0.0.1:6789/v1/chat/completions")
HERMES_API_KEY = os.getenv("HERMES_API_KEY", "")
HERMES_MODEL = os.getenv("HERMES_MODEL", "deepseek-chat")


def pick_llm() -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Return (url, key, model, name) for the first available LLM provider.

    Priority: Groq → DeepSeek → OpenAI → Local → Hermes
    Returns (None, None, None, None) if no provider is configured.
    """
    if GROQ_API_KEY:
        return GROQ_URL, GROQ_API_KEY, GROQ_MODEL, "Groq"
    if DEEPSEEK_API_KEY:
        return DEEPSEEK_URL, DEEPSEEK_API_KEY, DEEPSEEK_MODEL, "DeepSeek"
    if OPENAI_API_KEY:
        return OPENAI_URL, OPENAI_API_KEY, OPENAI_MODEL, "OpenAI"
    if LOCAL_LLM_URL:
        return LOCAL_LLM_URL, LOCAL_LLM_KEY, LOCAL_LLM_MODEL, "Local"
    if HERMES_API_KEY or HERMES_URL:
        return HERMES_URL, HERMES_API_KEY, HERMES_MODEL, "Hermes"
    return None, None, None, None


async def stream_chat(
    messages: list[dict],
    provider: Optional[str] = None,
    max_tokens: int = 120,
    temperature: float = 0.7,
    timeout: float = 30.0,
) -> AsyncIterator[str]:
    """Stream a chat completion from the active LLM provider.

    Yields text tokens (str) as they arrive. The first token typically
    arrives in 150-500ms depending on the provider.

    `messages` is the standard OpenAI format: [{"role": "system", ...}, {"role": "user", ...}]
    """
    url, key, model, name = pick_llm()
    if not url:
        raise RuntimeError(
            "No LLM provider configured. Set one of GROQ_API_KEY, DEEPSEEK_API_KEY, "
            "OPENAI_API_KEY, LOCAL_LLM_URL, or HERMES_URL in your .env"
        )
    if provider:
        name = provider

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}" if key else "Bearer not-needed",
        "User-Agent": "hermes-voice/0.1 (+https://github.com/Ex8-ca/hermes-voice)",
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }

    logger.info(f"LLM call → {name} ({model}), {len(messages)} msg, max_tokens={max_tokens}")
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise RuntimeError(f"LLM {name} returned {resp.status_code}: {body[:200].decode('utf-8', 'ignore')}")
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]  # strip "data: " prefix
                if data.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content")
                if content:
                    yield content
