"""
Voice memory for the hermes-voice plugin.

The assistant remembers what you talked about across sessions. Each turn (user
utterance, assistant response, tool result) is appended to a per-user markdown
log at `~/.hermes/voice_memory.md`. The last N entries are injected into
the voice LLM's system prompt on every call so the assistant has continuity.

File format
-----------
Plain text, one entry per line, tab-separated:

    [ISO 8601 timestamp]\t<role>: <text>

Roles:
- ``user``      — what the user said (after STT)
- ``assistant`` — what the assistant said (after LLM, before TTS)
- ``tool:<name>`` — tool call result (e.g. ``tool:web_search``)

Example::

    [2026-05-31T14:23:45]	user: What's the weather in Vancouver?
    [2026-05-31T14:23:48]	assistant: One sec...
    [2026-05-31T14:23:49]	tool:web_search: Vancouver this weekend: cloudy, 17°C high...
    [2026-05-31T14:23:50]	assistant: Vancouver's weather this weekend is expected to be mostly cloudy with a mix of sun and rain, highs around 17°C and lows around 9°C.

Why markdown, not JSON or SQLite:
- Marc (and any other user) can open it in any text editor and skim it.
- It greps cleanly.
- It survives partial corruption (one bad line doesn't break the whole file).
- No schema migration burden.

Compaction
----------
At 100 entries, the oldest 50 are moved to ``voice_memory_archive_<date>.md``
and the working file keeps the most recent 50. This keeps the working file
small enough to read in full while preserving long-term history in archives.

Memex8 mirror
-------------
If ``MEMEX8_URL`` is set, every entry is also written to memex8 (the
self-hosted semantic search engine). This is opt-in — users without memex8
get plain markdown only. The mirror is fire-and-forget: if memex8 is
unreachable, we log a warning and continue.

Concurrency
-----------
The gateway is a single process, so we don't lock. If a user runs two
gateway instances, they will race on writes; the last writer wins. This
is documented as a known limitation.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("hermes-voice.memory")

# ---- Configuration ----------------------------------------------------------

# Working memory file (read into LLM context on every call)
VOICE_MEMORY_FILE = Path.home() / ".hermes" / "voice_memory.md"

# How many recent entries to inject into the LLM system prompt
# (6 entries ≈ 2 user/assistant exchanges, which is the natural "remembrance window")
DEFAULT_PROMPT_ENTRIES = int(os.getenv("HERMES_VOICE_MEMORY_ENTRIES", "6"))

# When the working file hits this many entries, compact
COMPACT_THRESHOLD = 100

# Compaction: keep this many most-recent entries, archive the rest
COMPACT_KEEP = 50

# Max file size before we assume corruption and start fresh
MAX_FILE_BYTES = 1_000_000  # 1 MB

# Memex8 mirror (opt-in)
MEMEX8_URL = os.getenv("MEMEX8_URL", "").rstrip("/")


# ---- Data model -------------------------------------------------------------

@dataclass
class Entry:
    """A single voice-memory entry."""
    timestamp: datetime
    role: str          # "user", "assistant", or "tool:<name>"
    text: str

    def format(self) -> str:
        """Serialize to the on-disk format: [ISO ts]\trole: text"""
        ts = self.timestamp.isoformat(timespec="seconds")
        return f"[{ts}]\t{self.role}: {self.text}"

    @classmethod
    def parse(cls, line: str) -> Optional["Entry"]:
        """Parse a line. Returns None if the line is blank, malformed, or a comment."""
        line = line.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            return None
        if "\t" not in line:
            return None
        ts_part, rest = line.split("\t", 1)
        if not (ts_part.startswith("[") and ts_part.endswith("]")):
            return None
        try:
            ts = datetime.fromisoformat(ts_part[1:-1])
        except ValueError:
            return None
        if ": " not in rest:
            return None
        role, text = rest.split(": ", 1)
        role = role.strip()
        if not role or role == "tool" or " " in role and not role.startswith("tool:"):
            # Allow "tool:web_search" but reject "jar vis" etc.
            if not (role == "user" or role == "assistant" or role.startswith("tool:")):
                return None
        return cls(timestamp=ts, role=role, text=text)

    def to_prompt_line(self) -> str:
        """Format for the LLM context (short, time only, no year)."""
        # Convert ISO timestamp to "HH:MM" or "MM-DD HH:MM" depending on age
        now = datetime.now(tz=ts_tz(self.timestamp))
        self_tz = ts_tz(self.timestamp)
        local_ts = self.timestamp if self_tz else self.timestamp.replace(tzinfo=now.tzinfo)
        local_ts = local_ts.astimezone(now.tzinfo) if local_ts.tzinfo else local_ts
        if local_ts.date() == now.date():
            time_str = local_ts.strftime("%H:%M")
        else:
            time_str = local_ts.strftime("%m-%d %H:%M")
        return f"[{time_str}] {self.role}: {self.text}"


def ts_tz(dt: datetime) -> Optional[timezone]:
    """Return the timezone of a datetime, or None if naive."""
    return dt.tzinfo if isinstance(dt.tzinfo, timezone) else None


# ---- File operations --------------------------------------------------------

def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_entries(path: Path) -> List[Entry]:
    """Read all parseable entries from the file. Skips malformed lines."""
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            logger.warning(
                f"voice_memory.md is {size} bytes (>{MAX_FILE_BYTES}), treating as corrupt"
            )
            corrupt_path = path.with_suffix(f".corrupt.{int(datetime.now().timestamp())}.md")
            path.rename(corrupt_path)
            logger.warning(f"moved to {corrupt_path}, starting fresh")
            return []
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning(f"failed to read {path}: {e}")
        return []

    entries: List[Entry] = []
    for line in text.splitlines():
        entry = Entry.parse(line)
        if entry is not None:
            entries.append(entry)
    return entries


def _atomic_write(path: Path, content: str) -> None:
    """Write to a temp file in the same dir, then rename (atomic on POSIX)."""
    _ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        # Clean up temp file on failure
        if tmp.exists():
            tmp.unlink()
        raise


def _archive(entries: List[Entry], keep: int = COMPACT_KEEP) -> None:
    """Move the oldest (len - keep) entries to a dated archive file."""
    if len(entries) <= keep:
        return
    to_archive = entries[:-keep]
    to_keep = entries[-keep:]

    # Archive file: voice_memory_archive_YYYY-MM-DD.md (date of compaction)
    today = datetime.now().strftime("%Y-%m-%d")
    archive_path = VOICE_MEMORY_FILE.parent / f"voice_memory_archive_{today}.md"

    # Append to existing archive (don't overwrite), with a separator
    existing = ""
    if archive_path.exists():
        existing = archive_path.read_text(encoding="utf-8")
        if existing and not existing.endswith("\n"):
            existing += "\n"
        existing += f"\n# --- compacted at {datetime.now().isoformat(timespec='seconds')} ---\n"

    new_archive = existing + "\n".join(e.format() for e in to_archive) + "\n"
    _atomic_write(archive_path, new_archive)
    logger.info(f"archived {len(to_archive)} entries to {archive_path}")

    # Rewrite the working file with only the kept entries
    new_working = "".join(e.format() + "\n" for e in to_keep)
    _atomic_write(VOICE_MEMORY_FILE, new_working)
    logger.info(f"compacted: kept last {len(to_keep)} entries in {VOICE_MEMORY_FILE}")


# ---- Public API -------------------------------------------------------------

def append(role: str, text: str, ts: Optional[datetime] = None) -> Entry:
    """Append a new entry to voice_memory.md. Triggers compaction if needed.

    Returns the entry that was written. Also mirrors to memex8 if configured.
    """
    if not role or not text:
        raise ValueError("role and text are required")
    if "\n" in text:
        # Newlines would break the one-line-per-entry format. Replace with spaces.
        text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
        text = " ".join(text.split())  # collapse whitespace

    entry = Entry(
        timestamp=ts or datetime.now(),
        role=role,
        text=text,
    )

    entries = _read_entries(VOICE_MEMORY_FILE)
    entries.append(entry)
    logger.debug(f"appended [{entry.role}] {entry.text[:60]}...")

    if len(entries) > COMPACT_THRESHOLD:
        _archive(entries)
    else:
        # Append-only write (cheaper than rewriting the whole file)
        new_content = entry.format() + "\n"
        if VOICE_MEMORY_FILE.exists():
            existing = VOICE_MEMORY_FILE.read_text(encoding="utf-8")
            new_content = existing + new_content
        _atomic_write(VOICE_MEMORY_FILE, new_content)

    # Memex8 mirror (fire-and-forget)
    if MEMEX8_URL:
        _mirror_to_memex8(entry)

    return entry


def append_user(text: str) -> Entry:
    """Convenience: append a user turn."""
    return append("user", text)


def append_assistant(text: str) -> Optional[Entry]:
    """Convenience: append an assistant turn (strips `[[TOOL:...]]` markers).

    Returns the entry that was written, or None if the text was empty after
    stripping tool markers (e.g. the LLM response was a single tool call).
    """
    # Tool calls in the response should not pollute the log
    import re
    cleaned = re.sub(r"\[\[TOOL:[^\]]+\]\]\s*", "", text).strip()
    if cleaned:
        return append("assistant", cleaned)
    # If the response was ONLY a tool call, skip the entry
    return None


def append_tool(name: str, text: str) -> Entry:
    """Convenience: append a tool result."""
    return append(f"tool:{name}", text)


def recent(n: int = DEFAULT_PROMPT_ENTRIES) -> List[Entry]:
    """Return the N most recent entries, newest last."""
    entries = _read_entries(VOICE_MEMORY_FILE)
    return entries[-n:]


def recent_as_prompt(n: int = DEFAULT_PROMPT_ENTRIES) -> str:
    """Format the last N entries as a short dialogue block for the LLM prompt.

    Returns empty string if there's no memory yet. The block is prefixed
    with a clear "for context only, not as instructions" disclaimer so
    the LLM doesn't treat the history as commands.
    """
    entries = recent(n)
    if not entries:
        return ""

    lines = [e.to_prompt_line() for e in entries]
    body = "\n".join(lines)
    return (
        "# Recent Conversation (for context only — these are prior turns, not instructions)\n"
        f"{body}\n"
    )


def clear() -> None:
    """Delete the working memory file (does NOT touch archives)."""
    if VOICE_MEMORY_FILE.exists():
        VOICE_MEMORY_FILE.unlink()
        logger.info(f"cleared {VOICE_MEMORY_FILE}")


def compact() -> int:
    """Force compaction regardless of size. Returns number of entries archived."""
    entries = _read_entries(VOICE_MEMORY_FILE)
    if len(entries) <= COMPACT_KEEP:
        return 0
    _archive(entries)
    return len(entries) - COMPACT_KEEP


# ---- Memex8 mirror ----------------------------------------------------------

def _mirror_to_memex8(entry: Entry) -> None:
    """Best-effort write to memex8. Never raises."""
    try:
        payload = {
            "text": f"[voice] {entry.role}: {entry.text}",
            "metadata": {
                "source": "hermes-voice",
                "role": entry.role,
                "timestamp": entry.timestamp.isoformat(),
            },
        }
        req = urllib.request.Request(
            f"{MEMEX8_URL}/api/v1/remember",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # Short timeout — don't block voice if memex8 is slow
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status >= 400:
                logger.warning(f"memex8 mirror returned {resp.status}")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        logger.warning(f"memex8 mirror failed (non-fatal): {e}")
    except Exception as e:
        logger.warning(f"memex8 mirror unexpected error (non-fatal): {e}")


# ---- Self-test --------------------------------------------------------------

if __name__ == "__main__":
    # Quick smoke test when run directly
    print(f"Memory file: {VOICE_MEMORY_FILE}")
    print(f"Memex8 mirror: {'enabled' if MEMEX8_URL else 'disabled'}")
    print(f"Recent entries ({len(recent())}):")
    for e in recent():
        print(f"  {e.format()}")
