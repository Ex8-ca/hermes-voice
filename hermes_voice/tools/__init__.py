from __future__ import annotations
"""
Tool framework for hermes-voice.

The voice LLM emits tool requests as a single line of text:

    [[TOOL:tool_name arg1=value1 arg2=value2]]

The parser (`parse_tool_call`) extracts that line, the dispatcher
(`dispatch`) runs the named tool, and the result is fed back to the LLM
as a follow-up turn so it can continue normally.

Why text-based instead of native function-calling?
- Works with any chat model (Groq, DeepSeek, OpenAI, local, Hermes)
- The system prompt explains the syntax in plain English
- Simpler parsing, no tool_calls/tool message gymnastics
- Easier for users to add custom tools (just write a Python class)

Why a priority chain (memex8 → web → ask)?
- Your own memory usually has the answer (faster, more relevant)
- Web is the fallback when memory is empty
- Asking the user is a last resort
- Tools can declare priority; the dispatcher tries the first, then falls
  through if it returns nothing useful
"""
# Import base + registry + parser + dispatcher (always available)
from .base import Tool, ToolResult, ToolError
from .registry import REGISTRY, register, get_tool, list_tools
from .parser import parse_tool_call, strip_tool_call, TOOL_CALL_PATTERN
from .dispatcher import dispatch, dispatch_from_text, pick_filler, FILLER_PHRASES

# Auto-import built-in tool implementations so they self-register.
# If a user removes one of these files, the tool just won't be available.
import importlib
import logging

logger = logging.getLogger("hermes-voice.tools")

for _builtin in ("memex8_search", "web_search", "agentmail"):
    try:
        importlib.import_module(f".{_builtin}", package="hermes_voice.tools")
    except ImportError as e:
        logger.debug(f"Built-in tool '{_builtin}' not loaded: {e}")


__all__ = [
    "Tool",
    "ToolResult",
    "ToolError",
    "REGISTRY",
    "register",
    "get_tool",
    "list_tools",
    "parse_tool_call",
    "strip_tool_call",
    "TOOL_CALL_PATTERN",
    "dispatch",
    "dispatch_from_text",
    "pick_filler",
    "FILLER_PHRASES",
]
