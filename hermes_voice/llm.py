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
from typing import AsyncIterator, Callable, Optional, Tuple

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


# Ordered list of all configured providers. Used by
# stream_chat_with_fallback() to cycle through them when one hits 429.
def _all_providers() -> list[tuple[str, str, str, str]]:
    """Return [(url, key, model, name), ...] for every provider that has
    credentials configured, in priority order."""
    out: list[tuple[str, str, str, str]] = []
    if GROQ_API_KEY:     out.append((GROQ_URL, GROQ_API_KEY, GROQ_MODEL, "Groq"))
    if DEEPSEEK_API_KEY: out.append((DEEPSEEK_URL, DEEPSEEK_API_KEY, DEEPSEEK_MODEL, "DeepSeek"))
    if OPENAI_API_KEY:   out.append((OPENAI_URL, OPENAI_API_KEY, OPENAI_MODEL, "OpenAI"))
    if LOCAL_LLM_URL:    out.append((LOCAL_LLM_URL, LOCAL_LLM_KEY, LOCAL_LLM_MODEL, "Local"))
    if HERMES_API_KEY or HERMES_URL:
        out.append((HERMES_URL, HERMES_API_KEY, HERMES_MODEL, "Hermes"))
    return out


async def _stream_one_provider(
    url: str,
    key: str,
    model: str,
    name: str,
    messages: list[dict],
    max_tokens: int,
    temperature: float,
    timeout: float,
) -> AsyncIterator[str]:
    """Inner stream function. Raises RuntimeError on non-200. 429s are
    surfaced verbatim so the caller can decide whether to fall back."""
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
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise _ProviderHTTPError(name, resp.status_code, body[:300].decode("utf-8", "ignore"))
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
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


class _ProviderHTTPError(Exception):
    """Raised by _stream_one_provider when a provider returns non-200.
    Carries the status code so the fallback can decide."""
    def __init__(self, provider: str, status: int, body: str):
        self.provider = provider
        self.status = status
        self.body = body
        super().__init__(f"LLM {provider} returned {status}: {body[:200]}")


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

    If `provider` is given, only that provider is tried — even if it 429s
    the call will fail. Use `stream_chat_with_fallback()` for the cycling
    behavior used by the tool loop.
    """
    url, key, model, name = pick_llm()
    if not url or not key or not model or not name:
        raise RuntimeError(
            "No LLM provider configured. Set one of GROQ_API_KEY, DEEPSEEK_API_KEY, "
            "OPENAI_API_KEY, LOCAL_LLM_URL, or HERMES_URL in your .env"
        )
    if provider:
        # Look up the named provider instead of the first one
        for u, k, m, n in _all_providers():
            if n == provider:
                url, key, model, name = u, k, m, n
                break
        else:
            raise RuntimeError(f"Provider {provider!r} not configured")

    logger.info(f"LLM call → {name} ({model}), {len(messages)} msg, max_tokens={max_tokens}")
    try:
        async for token in _stream_one_provider(
            url, key, model, name, messages, max_tokens, temperature, timeout
        ):
            yield token
    except _ProviderHTTPError as e:
        raise RuntimeError(f"LLM {e.provider} returned {e.status}: {e.body[:200]}")


async def stream_chat_with_fallback(
    messages: list[dict],
    max_tokens: int = 120,
    temperature: float = 0.7,
    timeout: float = 30.0,
    *,
    on_fallback: Optional[Callable[[str, str], None]] = None,
) -> AsyncIterator[str]:
    """Stream a chat completion, falling back to other configured providers
    if the primary one hits a rate limit (HTTP 429) or a transient error.

    Tries each provider in priority order (Groq → DeepSeek → OpenAI →
    Local → Hermes). On 429/5xx/network error, moves to the next. On any
    other non-200 (e.g. 400 bad request) the error is re-raised immediately
    because falling back won't help with a malformed request.

    If `on_fallback` is given, it's called as on_fallback(failed_name,
    next_name) before each fallback, so the caller can announce the
    switch to the user ("trying a different model...") via filler TTS.

    Note: providers that already started streaming tokens are NOT swapped
    mid-stream — once we get a 200 and start receiving, we ride it out.
    """
    providers = _all_providers()
    if not providers:
        raise RuntimeError(
            "No LLM provider configured. Set one of GROQ_API_KEY, "
            "DEEPSEEK_API_KEY, OPENAI_API_KEY, LOCAL_LLM_URL, or "
            "HERMES_URL in your .env"
        )

    last_error: Optional[Exception] = None
    for i, (url, key, model, name) in enumerate(providers):
        logger.info(
            f"LLM call (try {i+1}/{len(providers)}) → {name} ({model}), "
            f"{len(messages)} msg, max_tokens={max_tokens}"
        )
        try:
            gen = _stream_one_provider(
                url, key, model, name, messages, max_tokens, temperature, timeout
            )
            # Pull at least one token before declaring success, so a 429
            # arriving AFTER the headers (rare but possible) is still
            # caught by the fallback chain.
            got_any = False
            async for token in gen:
                got_any = True
                yield token
            if not got_any:
                # Empty stream — treat as a soft failure and try the next
                last_error = RuntimeError(f"{name} returned empty stream")
                logger.warning(f"LLM {name}: empty stream, trying next provider")
                continue
            return
        except _ProviderHTTPError as e:
            last_error = RuntimeError(f"LLM {e.provider} returned {e.status}: {e.body[:200]}")
            # 429 or 5xx → try the next provider
            if e.status in (429, 500, 502, 503, 504) and i + 1 < len(providers):
                next_name = providers[i + 1][3]
                logger.warning(
                    f"LLM {name} returned {e.status}, falling back to {next_name}"
                )
                if on_fallback is not None:
                    try:
                        on_fallback(name, next_name)
                    except Exception:
                        pass
                continue
            # Non-retriable (400, 401, 403, etc.) — surface immediately
            raise
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as e:
            last_error = e
            if i + 1 < len(providers):
                next_name = providers[i + 1][3]
                logger.warning(
                    f"LLM {name} network error ({type(e).__name__}), falling back to {next_name}"
                )
                if on_fallback is not None:
                    try:
                        on_fallback(name, next_name)
                    except Exception:
                        pass
                continue
            raise

    # All providers exhausted
    if last_error:
        raise last_error
    raise RuntimeError("All LLM providers exhausted with no error captured")
