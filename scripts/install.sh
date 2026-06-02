#!/usr/bin/env bash
#
# Install the hermes-voice plugin into ~/.hermes/plugins/hermes-voice/
#
# What this does:
#   1. Copies the plugin source (hermes_voice/ from this repo) to
#      ~/.hermes/plugins/hermes-voice/ (so Hermes can find it).
#   2. Generates ~/.hermes/VOICE.md from the user's existing SOUL.md and
#      USER.md (if those exist), or copies the bundled generic default.
#   3. Installs Python dependencies.
#   4. Optionally installs systemd services (gateway + client).
#
# Usage:
#   ./scripts/install.sh                    # interactive (asks about systemd)
#   ./scripts/install.sh --no-systemd       # skip systemd setup
#   ./scripts/install.sh --regen-voice      # force-regenerate VOICE.md
#   ./scripts/install.sh --uninstall        # remove the plugin
#
set -euo pipefail

# ── Resolve paths ────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLUGIN_SRC="$REPO_ROOT/hermes_voice"
PLUGIN_DEST="$HOME/.hermes/plugins/hermes-voice"
HERMES_DIR="$HOME/.hermes"
VOICE_MD="$HERMES_DIR/VOICE.md"
SOUL_MD="$HERMES_DIR/SOUL.md"
USER_MD="$HERMES_DIR/USER.md"

# ── Parse args ───────────────────────────────────────────────────────
NO_SYSTEMD=0
REGEN_VOICE=0
UNINSTALL=0
for arg in "$@"; do
    case "$arg" in
        --no-systemd) NO_SYSTEMD=1 ;;
        --regen-voice) REGEN_VOICE=1 ;;
        --uninstall) UNINSTALL=1 ;;
        -h|--help)
            head -22 "$0" | tail -20
            exit 0
            ;;
        *) echo "Unknown arg: $arg" >&2; exit 1 ;;
    esac
done

# ── Uninstall ────────────────────────────────────────────────────────
if [ "$UNINSTALL" = "1" ]; then
    if [ -d "$PLUGIN_DEST" ]; then
        rm -rf "$PLUGIN_DEST"
        echo "✓ Removed $PLUGIN_DEST"
    else
        echo "Not installed at $PLUGIN_DEST — nothing to do"
    fi
    # Note: we do NOT remove VOICE.md — that's the user's file.
    echo "Note: ~/.hermes/VOICE.md was left in place. Delete it manually if you want."
    exit 0
fi

# ── Sanity checks ────────────────────────────────────────────────────
if [ ! -d "$PLUGIN_SRC" ]; then
    echo "ERROR: $PLUGIN_SRC not found. Run from inside the hermes-voice repo." >&2
    exit 1
fi

# ── Copy plugin source ──────────────────────────────────────────────
mkdir -p "$HOME/.hermes/plugins"
if [ -d "$PLUGIN_DEST" ]; then
    # Existing install — back it up, then replace
    BACKUP="${PLUGIN_DEST}.backup.$(date +%Y%m%d_%H%M%S)"
    mv "$PLUGIN_DEST" "$BACKUP"
    echo "→ Backed up existing install to $BACKUP"
fi
cp -r "$PLUGIN_SRC" "$PLUGIN_DEST"
echo "✓ Installed plugin to $PLUGIN_DEST"

# ── Generate VOICE.md ───────────────────────────────────────────────
mkdir -p "$HERMES_DIR"
if [ -f "$VOICE_MD" ] && [ "$REGEN_VOICE" = "0" ]; then
    echo "→ ~/.hermes/VOICE.md already exists — leaving it alone (use --regen-voice to overwrite)"
else
    if [ -f "$SOUL_MD" ]; then
        echo "→ Found ~/.hermes/SOUL.md — generating VOICE.md from it"
    elif [ -f "$USER_MD" ]; then
        echo "→ Found ~/.hermes/USER.md — generating VOICE.md from it"
    else
        echo "→ No SOUL.md or USER.md found — installing generic default VOICE.md"
    fi
    # Run the generator
    PYTHON_BIN="${HERMES_VOICE_PYTHON:-${PYTHON:-python3}}"
    "$PYTHON_BIN" -c "
import sys
sys.path.insert(0, '$PLUGIN_DEST')
from hermes_voice.install import generate_voice_md
result = generate_voice_md(force=True)
if result:
    print(f'✓ Generated {result} ({result.stat().st_size} bytes)')
"
fi

# ── Install Python dependencies ─────────────────────────────────────
PYTHON_BIN="${HERMES_VOICE_PYTHON:-${PYTHON:-python3}}"
echo "→ Installing Python dependencies..."
if [ -f "$REPO_ROOT/requirements-web.txt" ]; then
    "$PYTHON_BIN" -m pip install -q -r "$REPO_ROOT/requirements-web.txt" || true
fi
if [ -f "$REPO_ROOT/requirements-whisper.txt" ]; then
    "$PYTHON_BIN" -m pip install -q -r "$REPO_ROOT/requirements-whisper.txt" || true
fi

# ── Systemd services (optional) ────────────────────────────────────
if [ "$NO_SYSTEMD" = "0" ] && [ -d "$REPO_ROOT/systemd" ]; then
    echo
    echo "Optional: install systemd services (gateway + whisper + client)?"
    read -p "Install systemd services? [y/N] " REPLY
    if [[ "$REPLY" =~ ^[Yy]$ ]]; then
        for svc in "$REPO_ROOT/systemd/"*.service; do
            [ -f "$svc" ] || continue
            svc_name=$(basename "$svc")
            cp "$svc" "$HOME/.config/systemd/user/$svc_name"
            systemctl --user enable "$svc_name"
            systemctl --user start "$svc_name"
            echo "✓ Started $svc_name"
        done
        systemctl --user daemon-reload
    fi
fi

echo
echo "─────────────────────────────────────────────────────────"
echo "✓ Install complete"
echo
echo "Next steps:"
echo "  1. Edit ~/.hermes/VOICE.md if you want to customize the voice persona"
echo "  2. Configure LLM provider in ~/.hermes/hermes-voice.env or your .env"
echo "     (GROQ_API_KEY, DEEPSEEK_API_KEY, OPENAI_API_KEY, LOCAL_LLM_URL, or HERMES_URL)"
echo "  3. Start the gateway:"
echo "       cd $PLUGIN_DEST"
echo "       uvicorn hermes_voice.gateway:app --host 0.0.0.0 --port 8989"
echo "  4. Open http://localhost:8989/ in your browser"
echo "  5. (Optional) Run the desktop client on a separate machine:"
echo "       python3 $PLUGIN_DEST/hermes_voice/client.py"
echo "─────────────────────────────────────────────────────────"
