from __future__ import annotations
"""
Tool registry for hermes-voice.

Maps tool names to Tool instances. Tools are auto-registered via the
`@register` decorator when their module is imported, so users can drop
a new tool module in hermes_voice/tools/ and it just works.

The dispatcher uses `list_tools()` to render the system prompt's tool
list — tools with the lowest `priority` value run first; ties are
broken by registration order.
"""
import logging
from typing import Iterator, List

from .base import Tool

logger = logging.getLogger("hermes-voice.tools")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._insertion_order: list[str] = []

    def register(self, tool: Tool) -> None:
        """Register a Tool instance. If a tool with the same name is already
        registered, the new one replaces it (and we log a warning)."""
        if not tool.name:
            raise ValueError(f"Tool {type(tool).__name__} has no name; cannot register")
        if tool.name in self._tools:
            logger.warning(f"Replacing existing tool '{tool.name}' with {type(tool).__name__}")
        else:
            self._insertion_order.append(tool.name)
        self._tools[tool.name] = tool
        logger.info(f"Registered tool '{tool.name}' (priority={tool.priority})")

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> List[Tool]:
        """Return all tools, sorted by priority (lowest first), then registration order."""
        order = {name: i for i, name in enumerate(self._insertion_order)}
        return sorted(self._tools.values(), key=lambda t: (t.priority, order.get(t.name, 0)))

    def names(self) -> List[str]:
        return [t.name for t in self.list()]

    def clear(self) -> None:
        """Remove all registered tools. Primarily for testing."""
        self._tools.clear()
        self._insertion_order.clear()


# Module-level singleton
REGISTRY = ToolRegistry()


def register(tool) -> Tool:
    """Decorator: register a Tool class (instantiated automatically) or
    a Tool instance (used as-is).

    Class-based usage:
        @register
        class MyTool(Tool):
            name = "my_tool"
            ...

    Instance-based usage (for tools with state):
        register(MyTool(some_config))
    """
    # If we got a class (not an instance), instantiate it
    if isinstance(tool, type):
        tool = tool()
    if not isinstance(tool, Tool):
        raise TypeError(f"register() expected a Tool class or instance, got {type(tool).__name__}")
    REGISTRY.register(tool)
    return tool


def get_tool(name: str) -> Tool | None:
    return REGISTRY.get(name)


def list_tools() -> List[Tool]:
    return REGISTRY.list()
