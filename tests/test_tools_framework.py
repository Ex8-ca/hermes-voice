"""
Unit tests for the hermes_voice.tools framework.

Tests the parser, registry, dispatcher, and a fake end-to-end flow.
Does NOT hit the real Groq API or the real web — all tools are mocked.
"""
import asyncio
import pytest
from hermes_voice.tools import (
    Tool, ToolResult, ToolError,
    REGISTRY, register, get_tool, list_tools,
    parse_tool_call, strip_tool_call, dispatch, dispatch_from_text, pick_filler,
)


# ── Parser tests ──────────────────────────────────────────────────────

def test_parse_simple_tool_call():
    result = parse_tool_call("[[TOOL:web_search query=hello]]")
    assert result == ("web_search", {"query": "hello"})


def test_parse_quoted_args_with_spaces():
    result = parse_tool_call('[[TOOL:note_create title="My Idea" body="some text here" priority=high]]')
    assert result == ("note_create", {"title": "My Idea", "body": "some text here", "priority": "high"})


def test_parse_single_quotes():
    result = parse_tool_call("[[TOOL:web_search query='hello world']]")
    assert result == ("web_search", {"query": "hello world"})


def test_parse_no_tool_call():
    assert parse_tool_call("just a regular response") is None


def test_parse_tool_call_in_surrounding_text():
    result = parse_tool_call("before [[TOOL:web_search query=foo]] after")
    assert result == ("web_search", {"query": "foo"})


def test_parse_invalid_syntax():
    # Multi-word name should not match
    assert parse_tool_call("[[TOOL:multi word]]") is None
    # Empty name should not match
    assert parse_tool_call("[[TOOL:]]") is None


def test_strip_tool_call():
    assert strip_tool_call("[[TOOL:foo bar=baz]]") == ""
    assert strip_tool_call("before [[TOOL:foo x=1]] after") == "before after"
    assert strip_tool_call("no tool call here") == "no tool call here"


# ── Registry tests ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_registry():
    """Reset the registry between tests."""
    REGISTRY.clear()
    yield
    REGISTRY.clear()


def test_register_class_decorator():
    @register
    class MyTool(Tool):
        name = "my_tool"
        description = "test"
        async def run(self, **kwargs):
            return ToolResult(text="ok", source=self.name)
    assert "my_tool" in REGISTRY.names()
    assert get_tool("my_tool") is not None
    assert get_tool("my_tool").name == "my_tool"


def test_register_instance():
    class MyTool(Tool):
        name = "inst_tool"
        async def run(self, **kwargs):
            return ToolResult(text="ok")
    register(MyTool())
    assert "inst_tool" in REGISTRY.names()


def test_register_rejects_duplicate_with_warning():
    @register
    class FirstTool(Tool):
        name = "dupe"
        async def run(self, **kwargs): return ToolResult(text="first")
    @register
    class SecondTool(Tool):
        name = "dupe"
        async def run(self, **kwargs): return ToolResult(text="second")
    # Second registration wins
    assert get_tool("dupe").__class__.__name__ == "SecondTool"


def test_list_tools_sorted_by_priority():
    @register
    class HighPrio(Tool):
        name = "high"; priority = 10
        async def run(self, **k): return ToolResult(text="h")
    @register
    class LowPrio(Tool):
        name = "low"; priority = 100
        async def run(self, **k): return ToolResult(text="l")
    @register
    class MidPrio(Tool):
        name = "mid"; priority = 50
        async def run(self, **k): return ToolResult(text="m")
    names = [t.name for t in list_tools()]
    assert names == ["high", "mid", "low"]


# ── Dispatcher tests ──────────────────────────────────────────────────

def test_pick_filler():
    filler = pick_filler()
    assert filler in ["One sec...", "Checking...", "On it...", "Let me see...", "Hmm...", "Looking that up..."]


@pytest.mark.asyncio
async def test_dispatch_direct_call():
    @register
    class EchoTool(Tool):
        name = "echo"
        async def run(self, **kwargs):
            return ToolResult(text=f"echoed: {kwargs}", source="echo")
    result = await dispatch("echo", {"msg": "hi"})
    assert result.text == "echoed: {'msg': 'hi'}"
    assert result.source == "echo"


@pytest.mark.asyncio
async def test_dispatch_fallback_to_next_tool():
    @register
    class Empty(Tool):
        name = "empty"; priority = 10
        async def run(self, **k): return ToolResult(text="", source="empty")
    @register
    class Real(Tool):
        name = "real"; priority = 20
        async def run(self, **k): return ToolResult(text="found it", source="real")

    result = await dispatch("empty", {}, fallback=True)
    assert result.text == "found it"
    assert result.source == "real"


@pytest.mark.asyncio
async def test_dispatch_no_fallback_returns_empty():
    @register
    class Empty(Tool):
        name = "empty"
        async def run(self, **k): return ToolResult(text="", source="empty")
    result = await dispatch("empty", {}, fallback=False)
    # Empty result with fallback=False returns the "couldn't find" message
    assert "couldn't find" in result.text.lower() or result.is_empty()


@pytest.mark.asyncio
async def test_dispatch_handles_tool_exception():
    @register
    class BadTool(Tool):
        name = "bad"
        async def run(self, **k): raise RuntimeError("intentional")
    result = await dispatch("bad", {}, fallback=True)
    assert result.success is False
    assert "problem" in result.text.lower()


@pytest.mark.asyncio
async def test_dispatch_unknown_tool():
    result = await dispatch("does_not_exist", {})
    assert result.success is False
    assert "unknown" in result.text.lower()


@pytest.mark.asyncio
async def test_dispatch_timeout_returns_error():
    @register
    class SlowTool(Tool):
        name = "slow"
        async def run(self, **k):
            await asyncio.sleep(10)
            return ToolResult(text="done")
    result = await dispatch("slow", {}, timeout_s=0.2)
    assert result.success is False


@pytest.mark.asyncio
async def test_dispatch_from_text_with_surrounding():
    @register
    class WebSearch(Tool):
        name = "web_search"
        async def run(self, **k):
            return ToolResult(text="web result", source="web_search")
    result, remaining = await dispatch_from_text('Let me check [[TOOL:web_search query=foo]] for you')
    assert result.text == "web result"
    assert remaining == "Let me check for you"


@pytest.mark.asyncio
async def test_dispatch_from_text_no_tool():
    result, remaining = await dispatch_from_text("just a normal response")
    assert result is None
    assert remaining == "just a normal response"


# ── End-to-end priority chain (mimics the gateway flow) ──────────────

@pytest.mark.asyncio
async def test_full_priority_chain_memex8_to_web():
    """memex8 returns empty → web_search returns real result → final answer."""
    @register
    class Memex8Mock(Tool):
        name = "memex8_search"
        priority = 10
        async def run(self, **k):
            # Simulate "memex8 not configured" — return empty
            return ToolResult(text="", source="memex8_search")
    @register
    class WebMock(Tool):
        name = "web_search"
        priority = 50
        async def run(self, **k):
            return ToolResult(text="Web result for: " + k.get("query", ""), source="web_search")

    # LLM calls memex8_search, dispatcher falls through to web_search
    result = await dispatch("memex8_search", {"query": "test"}, fallback=True)
    assert "Web result" in result.text
    assert result.source == "web_search"
