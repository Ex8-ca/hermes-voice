"""
Install-time helper: generate ~/.hermes/VOICE.md from SOUL.md + USER.md.

When the hermes-voice plugin is installed, this module runs (via
`scripts/install.sh`) and creates a voice-focused persona file at
`~/.hermes/VOICE.md`. The generated VOICE.md is a tight distillation of
the user's existing persona — same voice, same values, but reformatted
for spoken conversation.

Generation rules:
- If ~/.hermes/SOUL.md exists: extract voice-relevant sections
- If ~/.hermes/USER.md exists: append as user context block
- If neither exists: copy the bundled generic VOICE.md
- If VOICE.md already exists: do not overwrite (user has customized it)

The "voice-relevant" extraction is intentionally simple — a string
filter, not an LLM call. We pick sections that explicitly mention
spoken interaction, brevity, directness, or the entity framing.
"""
import logging
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger("hermes-voice.install")

HERMES_DIR = Path.home() / ".hermes"
SOUL_MD = HERMES_DIR / "SOUL.md"
USER_MD = HERMES_DIR / "USER.md"
VOICE_MD = HERMES_DIR / "VOICE.md"

# Bundled generic VOICE.md lives next to this module.
# Used as the fallback when the user has no SOUL.md or USER.md.
BUNDLED_VOICE_MD = Path(__file__).resolve().parent / "install" / "VOICE.md.default"

# Sections from SOUL.md that are voice-relevant (substring match on
# the section header or a key phrase in the body). Keeps the
# distillation deterministic — no LLM call needed at install time.
VOICE_RELEVANT_SECTIONS = [
    ("Core Truths", "Be genuinely helpful"),
    ("Core Truths", "Have opinions"),
    ("Boundaries", "Private things stay private"),
    ("Vibe", "concise"),
    ("Honesty", "Be honest about uncertainty"),
    ("Honesty", "Real questions deserve real answers"),
    ("Your Specific Personality", "Honest disagreement over validation"),
    ("Your Specific Personality", "Directness over performance"),
    ("Your Specific Personality", "Substance over optics"),
    ("Your Specific Personality", "entity"),
]


def _extract_voice_sections(soul_text: str) -> str:
    """Pull the voice-relevant sections out of SOUL.md.

    Keeps section headers and bodies for the matches in
    VOICE_RELEVANT_SECTIONS. Drops everything else (memex8 docs,
    cron rules, technical operating procedures).
    """
    lines = soul_text.split("\n")
    keep_lines: list[str] = []
    current_section: Optional[str] = None
    current_body: list[str] = []
    current_kept = False
    in_code_block = False

    def flush():
        if current_kept and current_section:
            keep_lines.append(f"## {current_section}")
            keep_lines.extend(current_body)

    for line in lines:
        # Track fenced code blocks (don't mistake ``` for headers)
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            if current_kept:
                current_body.append(line)
            continue
        if in_code_block:
            if current_kept:
                current_body.append(line)
            continue

        # Section header: "# Title" or "## Title"
        if line.startswith("#") and not line.startswith("#!"):
            flush()
            current_section = line.lstrip("#").strip()
            current_body = []
            # Is this section voice-relevant?
            current_kept = any(
                section.lower() in current_section.lower() or phrase.lower() in current_section.lower()
                for section, phrase in VOICE_RELEVANT_SECTIONS
            )
            continue

        if current_kept:
            # Also keep body lines that contain voice-relevant phrases
            # (catches "honest disagreement" even if it's in a different section)
            if any(phrase.lower() in line.lower() for _, phrase in VOICE_RELEVANT_SECTIONS):
                current_body.append(line)
            elif current_body:  # we're inside a kept section, accumulate
                current_body.append(line)

    flush()

    extracted = "\n".join(keep_lines).strip()
    if not extracted:
        return ""

    # Add a header explaining this was generated
    return (
        "# VOICE.md — Generated from SOUL.md\n"
        "# This is a voice-focused distillation of your full persona. The full\n"
        "# version is at ~/.hermes/SOUL.md. To customize the voice version,\n"
        "# edit this file directly — it will not be regenerated unless you\n"
        "# delete it and re-run the installer.\n"
        "\n"
        f"{extracted}\n"
    )


def _read_user_context() -> str:
    """Read USER.md and return it as a User Context block, or empty string."""
    if not USER_MD.exists():
        return ""
    text = USER_MD.read_text(encoding="utf-8").strip()
    if not text:
        return ""
    return f"\n\n# User Context (from ~/.hermes/USER.md)\n\n{text}\n"


def generate_voice_md(*, force: bool = False) -> Optional[Path]:
    """Generate ~/.hermes/VOICE.md from the user's existing persona files.

    Returns:
        Path to the generated VOICE.md, or None if no generation happened
        (e.g. VOICE.md already exists and force=False).

    Behaviour:
    - If VOICE.md exists and force=False: no-op, returns None
    - If SOUL.md exists: extract voice-relevant sections + add USER.md
    - If only USER.md exists: just USER.md as user context + generic prefix
    - If neither exists: copy the bundled default VOICE.md
    """
    if VOICE_MD.exists() and not force:
        logger.info(f"VOICE.md already exists at {VOICE_MD} — skipping (use force=True to overwrite)")
        return None

    HERMES_DIR.mkdir(parents=True, exist_ok=True)

    if SOUL_MD.exists():
        soul_text = SOUL_MD.read_text(encoding="utf-8")
        persona = _extract_voice_sections(soul_text)
        if not persona:
            logger.warning(f"SOUL.md found but no voice-relevant sections extracted — falling back to default")
            persona = ""
    else:
        persona = ""

    user_context = _read_user_context()

    if not persona:
        # Fall back to bundled default
        if BUNDLED_VOICE_MD.exists():
            default = BUNDLED_VOICE_MD.read_text(encoding="utf-8")
            content = default + user_context
            VOICE_MD.write_text(content, encoding="utf-8")
            logger.info(f"Generated VOICE.md from bundled default + USER.md at {VOICE_MD}")
        else:
            # Last resort: inline generic persona (no bundled file yet)
            content = (
                "# VOICE.md — Voice Persona (generic fallback)\n\n"
                "You are a voice assistant. Keep responses SHORT — under 30 words. "
                "Speak conversationally. Be direct. No filler.\n"
            ) + user_context
            VOICE_MD.write_text(content, encoding="utf-8")
            logger.info(f"Generated VOICE.md from inline fallback at {VOICE_MD}")
    else:
        # Voice-relevant sections from SOUL.md + USER.md context
        content = persona + user_context
        VOICE_MD.write_text(content, encoding="utf-8")
        logger.info(f"Generated VOICE.md from SOUL.md + USER.md at {VOICE_MD}")

    return VOICE_MD


if __name__ == "__main__":
    # Allow running directly: `python -m hermes_voice.install`
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import sys
    force = "--force" in sys.argv
    result = generate_voice_md(force=force)
    if result:
        print(f"✓ Generated {result} ({result.stat().st_size} bytes)")
    else:
        print("VOICE.md already exists, skipping. Use --force to overwrite.")
