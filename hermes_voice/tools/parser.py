from __future__ import annotations
"""
Parser for the text-based tool-call syntax.

The voice LLM emits tool requests as a single line of text:

    [[TOOL:tool_name arg1=value1 arg2=value2]]

This is intentionally simple — no JSON, no function-calling API, no
escaping. If the user needs to put a quote in an argument, they can
use single quotes: arg='hello world'.

The full grammar:

    TOOL_CALL   := "[[TOOL:" TOOL_NAME ARGS "]]"
    TOOL_NAME   := identifier (letters, digits, underscores)
    ARGS        := (WS+ ARG)*
    ARG         := KEY "=" VALUE
    KEY         := identifier
    VALUE       := QUOTED | UNQUOTED
    QUOTED      := '"' [^"]* '"' | "'" [^']* "'"
    UNQUOTED    := [^\\s\\]]+

The parser returns (tool_name, kwargs) or None if no tool call is
present. Only the FIRST tool call on a line is returned — the
dispatcher is called once per turn.

Why text-based instead of native function-calling?
- Works with any chat model (no tool_calls API dependency)
- Simpler to debug (you can see exactly what the LLM emitted)
- Easier for users to add their own tools (just write Python)
- Lower first-token latency (no JSON schema validation)
"""
import re
from typing import Optional, Dict, Tuple

# Match a single [[TOOL:name arg=val ...]] on its own line.
# Captures: tool name, then everything between the name and the closing ]]
TOOL_CALL_PATTERN = re.compile(
    r"\[\[TOOL:"                    # opening marker
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"  # tool name
    r"(?P<args>(?:\s+[A-Za-z_][A-Za-z0-9_]*="  # arg name=value
    r"(?:\"[^\"]*\"|'[^']*'|[^\s\]]+))*"
    r")"
    r"\]\]"                         # closing marker
)


def parse_tool_call(text: str) -> Optional[tuple[str, dict[str, str]]]:
    """Extract the first tool call from `text`.

    Returns (tool_name, kwargs) or None if no valid tool call is present.

    Only matches a tool call on its own line (between newlines or at the
    start/end of the string). Other text in `text` is ignored — callers
    should strip the tool call from the response and feed the rest back
    to the user as the LLM's "thinking" or surrounding context.
    """
    m = TOOL_CALL_PATTERN.search(text)
    if not m:
        return None

    name = m.group("name")
    args_str = m.group("args") or ""
    kwargs = parse_args(args_str)
    return name, kwargs


def parse_args(args_str: str) -> Dict[str, str]:
    """Parse 'key1=val1 key2=val2 ...' into a dict.

    Values can be quoted (single or double) or unquoted (no whitespace).
    Quoted values keep their quotes stripped. Everything is a string —
    tools are responsible for casting to int/float/bool if needed.
    """
    kwargs: dict[str, str] = {}
    if not args_str.strip():
        return kwargs

    # Walk character by character to handle quoted values with spaces
    i = 0
    n = len(args_str)
    while i < n:
        # Skip whitespace
        while i < n and args_str[i].isspace():
            i += 1
        if i >= n:
            break

        # Read key (until '=')
        key_start = i
        while i < n and args_str[i] != "=" and not args_str[i].isspace():
            i += 1
        if i >= n or args_str[i] != "=":
            # Malformed: no '=' for this key. Skip to next whitespace.
            continue
        key = args_str[key_start:i]
        i += 1  # skip '='

        # Read value
        if i >= n:
            kwargs[key] = ""
            break
        if args_str[i] in ('"', "'"):
            quote = args_str[i]
            i += 1
            val_start = i
            while i < n and args_str[i] != quote:
                i += 1
            kwargs[key] = args_str[val_start:i]
            if i < n:
                i += 1  # skip closing quote
        else:
            val_start = i
            while i < n and not args_str[i].isspace():
                i += 1
            kwargs[key] = args_str[val_start:i]

    return kwargs


def strip_tool_call(text: str) -> str:
    """Remove the first tool call from `text` and return the rest, trimmed."""
    m = TOOL_CALL_PATTERN.search(text)
    if not m:
        return text.strip()
    # Splice out the match and clean up
    before = text[:m.start()].rstrip()
    after = text[m.end():].lstrip()
    return (before + " " + after).strip() if (before and after) else (before or after)
