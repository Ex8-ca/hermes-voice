"""
web_search tool: search the public web for information.

Priority: 50 (medium — runs after memex8_search if that returns empty)

Uses a configurable search backend:
- TAVILY_API_KEY → Tavily (AI-optimized search, returns clean snippets)
- SEARXNG_URL → self-hosted SearXNG (no API key, no rate limit)
- Otherwise → DuckDuckGo HTML scraping (no key, rate-limited, fragile)

The tool returns 3-5 short snippets, not full web pages. The LLM is
expected to summarize for voice — not read snippets aloud.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from .base import Tool, ToolResult
from .registry import register

logger = logging.getLogger("hermes-voice.tools.web_search")


@register
class WebSearchTool(Tool):
    name = "web_search"
    description = "Search the public web. Returns a few short snippets, not full pages. Use only after memex8 returned nothing."
    priority = 50
    examples = [
        '[[TOOL:web_search query="Tesla Model 3 audio upgrade 2024"]]',
        '[[TOOL:web_search query="weather in Vancouver this weekend"]]',
    ]

    async def run(self, query: str = "", limit: str = "3", **kwargs: Any) -> ToolResult:
        """Search the web for `query`.

        Args:
            query: Search query (natural language or keywords)
            limit: Max snippets to return (default 3, max 5)
        """
        if not query.strip():
            return ToolResult(text="", success=True, source=self.name)

        try:
            limit_int = max(1, min(5, int(limit)))
        except (ValueError, TypeError):
            limit_int = 3

        # Try Tavily first (cleanest API)
        tavily_key = os.getenv("TAVILY_API_KEY", "")
        if tavily_key:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        "https://api.tavily.com/search",
                        json={
                            "api_key": tavily_key,
                            "query": query,
                            "max_results": limit_int,
                            "include_answer": False,
                            "search_depth": "basic",
                        },
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        results = data.get("results", [])
                        if not results:
                            return ToolResult(text="", success=True, source=self.name)
                        lines = [f"Web search ({len(results)} result{'s' if len(results) != 1 else ''}):"]
                        for r in results[:limit_int]:
                            title = r.get("title", "").strip()
                            content = r.get("content", "").strip()
                            url = r.get("url", "").strip()
                            if title and content:
                                lines.append(f"- {title}: {content[:200]}")
                            elif content:
                                lines.append(f"- {content[:200]}")
                            if url:
                                lines.append(f"  ({url})")
                        return ToolResult(
                            text="\n".join(lines),
                            success=True,
                            data={"results": results},
                            source=self.name,
                        )
            except Exception as e:
                logger.warning(f"Tavily search failed: {e}")

        # Try self-hosted SearXNG next
        searxng_url = os.getenv("SEARXNG_URL", "")
        if searxng_url:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        f"{searxng_url.rstrip('/')}/search",
                        params={"q": query, "format": "json", "categories": "general"},
                        headers={"User-Agent": "hermes-voice/0.1"},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        results = data.get("results", [])
                        if not results:
                            return ToolResult(text="", success=True, source=self.name)
                        lines = [f"Web search ({len(results)} result{'s' if len(results) != 1 else ''}):"]
                        for r in results[:limit_int]:
                            title = r.get("title", "").strip()
                            content = r.get("content", "").strip()
                            url = r.get("url", "").strip()
                            if title and content:
                                lines.append(f"- {title}: {content[:200]}")
                            elif content:
                                lines.append(f"- {content[:200]}")
                            if url:
                                lines.append(f"  ({url})")
                        return ToolResult(text="\n".join(lines), success=True, source=self.name)
            except Exception as e:
                logger.warning(f"SearXNG search failed: {e}")

        # Last resort: DuckDuckGo HTML (no key, fragile, no rate limit handling)
        try:
            import httpx
            async with httpx.AsyncClient(
                timeout=10.0,
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) hermes-voice/0.1"},
                follow_redirects=True,
            ) as client:
                resp = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                )
                if resp.status_code == 200:
                    # Minimal HTML parse — just grab result snippets via regex
                    import re
                    snippets = re.findall(
                        r'class="result__snippet"[^>]*>(.*?)</a>',
                        resp.text,
                        re.DOTALL,
                    )
                    # Strip HTML tags from snippets
                    snippets = [re.sub(r"<[^>]+>", "", s).strip() for s in snippets]
                    snippets = [s for s in snippets if s][:limit_int]
                    if not snippets:
                        return ToolResult(text="", success=True, source=self.name)
                    lines = [f"Web search ({len(snippets)} result{'s' if len(snippets) != 1 else ''}):"]
                    for s in snippets:
                        lines.append(f"- {s[:200]}")
                    return ToolResult(text="\n".join(lines), success=True, source=self.name)
        except Exception as e:
            logger.warning(f"DuckDuckGo search failed: {e}")

        return ToolResult(text="", success=True, source=self.name)
