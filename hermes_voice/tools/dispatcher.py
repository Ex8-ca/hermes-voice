"""
Tool dispatcher for hermes-voice.

The dispatcher is the runtime glue between the LLM's `[[TOOL:...]]`
emission and the actual tool execution. It:

1. Picks a filler phrase (when the tool is going to take time)
2. Calls the tool's async `run(**kwargs)` method
3. Handles errors gracefully (timeout, exception, empty result)
4. Falls through the priority chain if a tool returns nothing
5. Returns a ToolResult the gateway can feed back to the LLM

The "priority chain" behaviour: when the dispatcher is called with
just a tool NAME, it runs that tool. When called without a name
(or with `fallback=True`), it walks the registry from highest priority
(lowest number) to lowest, stopping at the first tool that returns
a non-empty result.

Example: the LLM emits just `[[TOOL:lookup]]` (a generic "find an
answer" tool). The dispatcher:
- Tries memex8_search first (priority 10)
- If empty, tries web_search (priority 50)
- If both empty, returns "I couldn't find that anywhere"
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Optional

from .base import Tool, ToolResult, ToolError
from .registry import REGISTRY, get_tool, list_tools

logger = logging.getLogger("hermes-voice.dispatcher")

# Filler phrases played immediately when a tool starts. The LLM is told
# (in VOICE.md) that these will play — the user hears something, the
# silence is masked while the tool runs.
FILLER_PHRASES = [
    "One sec...",
    "Checking...",
    "On it...",
    "Let me see...",
    "Hmm...",
    "Looking that up...",
]


def pick_filler() -> str:
    """Return a random filler phrase from the list."""
    return random.choice(FILLER_PHRASES)


async def dispatch(
    tool_name: Optional[str] = None,
    kwargs: Optional[dict] = None,
    *,
    fallback: bool = True,
    timeout_s: float = 15.0,
) -> ToolResult:
    """Run a tool by name (or run the priority chain if fallback=True).

    Args:
        tool_name: Specific tool to run. If None, walks the priority chain.
        kwargs: Arguments to pass to the tool. All values are strings —
            tools are responsible for casting to int/float/bool.
        fallback: If True and tool_name returns empty, try the next tool
            in the priority chain. If False, just return whatever the
            named tool produced.
        timeout_s: Hard timeout for the entire dispatch operation.

    Returns:
        ToolResult with text (empty if no tool produced anything) and
        source (the name of the tool that ran, or None).
    """
    kwargs = kwargs or {}
    candidates: list[Tool] = []

    if tool_name:
        tool = get_tool(tool_name)
        if tool is None:
            available = ", ".join(REGISTRY.names()) or "(none registered)"
            return ToolResult(
                text=f"Unknown tool '{tool_name}'. Available: {available}.",
                success=False,
                source=None,
            )
        candidates.append(tool)
        if fallback:
            # Append the rest in priority order, skipping the named one
            for t in list_tools():
                if t.name != tool_name:
                    candidates.append(t)
    else:
        candidates = list_tools()

    if not candidates:
        return ToolResult(
            text="No tools are registered. Configure a tool module to enable this feature.",
            success=False,
            source=None,
        )

    last_error: Optional[Exception] = None
    for tool in candidates:
        try:
            result = await asyncio.wait_for(
                tool.run(**kwargs),
                timeout=timeout_s,
            )
            if not result.is_empty():
                logger.info(f"Tool '{tool.name}' produced result ({len(result.text)} chars)")
                return result
            logger.debug(f"Tool '{tool.name}' returned empty, trying next")
        except ToolError as e:
            logger.warning(f"Tool '{tool.name}' raised ToolError: {e}")
            last_error = e
            continue
        except asyncio.TimeoutError:
            logger.warning(f"Tool '{tool.name}' timed out after {timeout_s}s")
            last_error = TimeoutError(f"{tool.name} took >{timeout_s}s")
            continue
        except Exception as e:
            logger.exception(f"Tool '{tool.name}' raised unexpected error")
            last_error = e
            continue

    # All candidates returned empty or errored
    if last_error:
        return ToolResult(
            text=f"I tried to look that up but ran into a problem: {last_error}",
            success=False,
            source=candidates[0].name if candidates else None,
        )
    return ToolResult(
        text="I couldn't find that anywhere I know to look. Could you rephrase, or want me to try a different angle?",
        success=True,
        source=None,
    )


async def dispatch_from_text(
    text: str,
    *,
    fallback: bool = True,
    timeout_s: float = 15.0,
) -> tuple[Optional[ToolResult], str]:
    """Parse a tool call from `text` and dispatch it.

    Returns (result, remaining_text):
        - result: ToolResult or None if no tool call was present
        - remaining_text: the original text with the tool call stripped
    """
    from .parser import parse_tool_call, strip_tool_call

    parsed = parse_tool_call(text)
    if parsed is None:
        return None, text

    tool_name, kwargs = parsed
    remaining = strip_tool_call(text)
    result = await dispatch(tool_name, kwargs, fallback=fallback, timeout_s=timeout_s)
    return result, remaining
