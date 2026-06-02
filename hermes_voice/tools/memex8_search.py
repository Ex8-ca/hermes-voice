"""
memex8_search tool: search the user's persistent memory.

Priority: 10 (highest — runs first)

If the user has memex8 running and configured, this tool queries it
for memories relevant to the query. If memex8 is not available, the
tool returns an empty result (forcing fallback to web_search).

The memex8 system is exposed by Hermes (the host agent). We look for
it via:
1. The `memex8_search` Python module (if installed in the same venv)
2. The memex8 HTTP API (if MEMEX8_URL is set in env)

For now, this is a stub that returns empty — the actual memex8
integration is owned by Hermes core and not part of this plugin.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from .base import Tool, ToolResult
from .registry import register

logger = logging.getLogger("hermes-voice.tools.memex8_search")


@register
class Memex8SearchTool(Tool):
    name = "memex8_search"
    description = "Search your own persistent memory for context relevant to the query. Returns the top N matches."
    priority = 10  # highest priority — runs first
    examples = [
        '[[TOOL:memex8_search query="what did we work on last week"]]',
        '[[TOOL:memex8_search query="Zentropy propulsion notes"]]',
    ]

    async def run(self, query: str = "", limit: str = "3", **kwargs: Any) -> ToolResult:
        """Search memex8 for memories matching the query.

        Args:
            query: Natural language search query
            limit: Max number of results to return (default 3, max 10)
        """
        if not query.strip():
            return ToolResult(text="", success=True, source=self.name)

        try:
            limit_int = max(1, min(10, int(limit)))
        except (ValueError, TypeError):
            limit_int = 3

        # Try the memex8 HTTP API first
        memex8_url = os.getenv("MEMEX8_URL", "")
        if memex8_url:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(
                        f"{memex8_url.rstrip('/')}/search",
                        json={"query": query, "limit": limit_int},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        results = data.get("results", [])
                        if not results:
                            return ToolResult(text="", success=True, source=self.name)
                        # Format the results for the LLM
                        lines = [f"From your memory ({len(results)} match{'es' if len(results) != 1 else ''}):"]
                        for r in results[:limit_int]:
                            text = r.get("text", "").strip()
                            if text:
                                lines.append(f"- {text}")
                                source = r.get("source") or r.get("path")
                                if source:
                                    lines.append(f"  (source: {source})")
                        return ToolResult(
                            text="\n".join(lines),
                            success=True,
                            data={"results": results},
                            source=self.name,
                        )
            except Exception as e:
                logger.warning(f"memex8 HTTP query failed: {e}")

        # Try the local Python module (if memex8 is installed alongside)
        try:
            from memex8 import search  # type: ignore
            results = search(query, limit=limit_int)
            if not results:
                return ToolResult(text="", success=True, source=self.name)
            lines = [f"From your memory ({len(results)} match{'es' if len(results) != 1 else ''}):"]
            for r in results:
                text = r.get("text", "").strip() if isinstance(r, dict) else str(r).strip()
                if text:
                    lines.append(f"- {text}")
            return ToolResult(text="\n".join(lines), success=True, source=self.name)
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"memex8 module query failed: {e}")

        # memex8 unavailable — return empty so dispatcher falls through to web_search
        logger.debug("memex8 not available; returning empty (dispatcher will try web_search)")
        return ToolResult(text="", success=True, source=self.name)
