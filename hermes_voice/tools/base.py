from __future__ import annotations
"""
Base classes for hermes-voice tools.

A tool is a single async function the LLM can call. Tools are pure
async functions (no shared state, no class instances). To create a tool:

1. Subclass `Tool` and implement `async def run(self, **kwargs) -> ToolResult`
2. Set `name`, `description`, `priority` (lower runs first)
3. Decorate with `@register` or call `REGISTRY.register(MyTool())`

The dispatcher calls `tool.run(**kwargs)` and either gets a ToolResult
or raises a ToolError. ToolResults with `success=False` or empty
`text` cause the dispatcher to try the next tool in the priority chain.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("hermes-voice.tools")


class ToolError(Exception):
    """Raised by a tool's `run()` method when the tool fails."""
    pass


@dataclass
class ToolResult:
    """The result of running a tool.

    Attributes:
        text: Plain text result to feed back to the LLM. If empty and
            `success=True`, the dispatcher will try the next tool.
        success: True if the tool ran (even if it found nothing).
            False means the tool itself failed (exception, timeout, etc.)
        data: Optional structured data (e.g. the raw search results).
            The LLM doesn't see this; useful for callers.
        source: Which tool produced this (for debugging/observability).
    """
    text: str
    success: bool = True
    data: Optional[dict] = None
    source: Optional[str] = None

    def is_empty(self) -> bool:
        """True if this result has no useful text for the LLM."""
        return not self.text or not self.text.strip()


class Tool:
    """Base class for all voice tools.

    Subclasses must set:
    - name: short identifier (e.g. "memex8_search")
    - description: one-line description for the system prompt
    - priority: lower runs first (default 100); 10-50 is high priority

    Subclasses must implement:
    - async def run(self, **kwargs) -> ToolResult
    """

    name: str = ""
    description: str = ""
    priority: int = 100  # lower = higher priority; runs first
    examples: list[str] = []  # example invocations shown to the LLM

    async def run(self, **kwargs) -> ToolResult:
        """Execute the tool. Override in subclasses.

        Should return a ToolResult. If you can't find what was asked for,
        return ToolResult(text="", success=True) — the dispatcher will
        try the next tool in the priority chain.
        """
        raise NotImplementedError

    def to_system_prompt(self) -> str:
        """Render this tool for the LLM's system prompt."""
        lines = [
            f"{self.name}: {self.description}",
            f"  priority: {self.priority}",
        ]
        if self.examples:
            lines.append(f"  example: {self.examples[0]}")
        return "\n".join(lines)
