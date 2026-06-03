#!/usr/bin/env bash
# bootstrap.sh — one-shot installer for hermes-voice dependencies.
#
# What this does:
#   1. Detect Python (3.10+) and create a venv if one doesn't exist
#   2. Install the right requirements files for gateway + whisper + (optional) client
#   3. Verify ctranslate2 version (4.7.2+ required for RTX 40/50 series)
#   4. Probe WHISPER_URL — if unreachable, offer to install + start whisper-server
#   5. Set WHISPER_URL in .env if missing
#   6. Optional: download the default Whisper model so first run is fast
#
# Idempotent: safe to run multiple times. Each step checks before acting.
#
# Usage:
#   ./bootstrap.sh                  # interactive — prompts for client install
#   ./bootstrap.sh --yes            # non-interactive — accept all defaults
#   ./bootstrap.sh --no-client      # skip the optional desktop client
#   ./bootstrap.sh --whisper-port 9001
#
# Exit codes:
#   0 = success
#   1 = python missing or too old
#   2 = pip install failed
#   3 = user declined required step

set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${HERMES_VOICE_VENV:-$SCRIPT_DIR/venv}"
PYTHON="${PYTHON:-python3}"
WHISPER_PORT="${WHISPER_PORT:-9001}"
WHISPER_MODEL="${WHISPER_MODEL:-mobiuslabsgmbh/faster-whisper-large-v3-turbo}"
INSTALL_CLIENT=0
ASSUME_YES=0
DOWNLOAD_MODEL=0

# ── Arg parse ────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes|-y)        ASSUME_YES=1; shift ;;
        --no-client)     INSTALL_CLIENT=0; shift ;;
        --with-client)   INSTALL_CLIENT=1; shift ;;
        --download-model) DOWNLOAD_MODEL=1; shift ;;
        --whisper-port)  WHISPER_PORT="$2"; shift 2 ;;
        --venv)          VENV_DIR="$2"; shift 2 ;;
        --python)        PYTHON="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,25p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "Unknown arg: $1" >&2
            exit 1
            ;;
    esac
done

# ── Helpers ──────────────────────────────────────────────────────────────
# (colors are written directly as ANSI escapes — bash double-quoted strings
# don't reliably interpret \033 as ESC, so we just use the raw bytes)

step() { printf '\n\033[0;32m▶\033[0m %s\n' "$1"; }
warn() { printf '\033[0;33m⚠\033[0m  %s\n' "$1"; }
err()  { printf '\033[0;31m✗\033[0m  %s\n' "$1" >&2; }
dim()  { printf '\033[2m  %s\033[0m\n' "$1"; }
ask() {
    if [[ "$ASSUME_YES" == "1" ]]; then
        REPLY="y"
        return 0
    fi
    local prompt="$1"
    printf '\033[0;33m?\033[0m  %s [y/N] ' "$prompt"
    read -n 1 -r
    echo
    [[ "$REPLY" =~ ^[Yy]$ ]]
}

# ── Step 1: Python check ────────────────────────────────────────────────
step "Checking Python..."
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    err "Python not found in PATH (looked for: $PYTHON)"
    err "Install Python 3.10+ and re-run, or set PYTHON=/path/to/python3"
    exit 1
fi

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$("$PYTHON" -c "import sys; print(sys.version_info.major)")
PY_MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")

if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 10 ]]; }; then
    err "Python $PY_VERSION found, but hermes-voice requires 3.10+"
    exit 1
fi
dim "Python $PY_VERSION at $(command -v "$PYTHON")"

# ── Step 2: venv ────────────────────────────────────────────────────────
step "Setting up virtualenv at $VENV_DIR..."
if [[ -d "$VENV_DIR" ]]; then
    dim "Already exists — reusing"
else
    "$PYTHON" -m venv "$VENV_DIR"
    dim "Created"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# Some venvs (e.g. created without ensurepip) have no `pip` binary. Fall
# back to `python -m pip` in that case so bootstrap works regardless of
# how the venv was made. Also detect broken shebangs (e.g. pip script
# pointing to a different venv that no longer exists).
PIP=""
if [[ -x "$VENV_DIR/bin/pip" ]] && "$VENV_DIR/bin/pip" --version >/dev/null 2>&1; then
    PIP="$VENV_DIR/bin/pip"
elif "$VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1; then
    PIP="$VENV_DIR/bin/python -m pip"
    if [[ -x "$VENV_DIR/bin/pip" ]]; then
        warn "Found broken pip script (wrong shebang) — using 'python -m pip' instead."
        warn "Run to fix: $PIP install --force-reinstall pip"
    fi
else
    err "pip not available in venv and 'python -m pip' also fails."
    err "Re-create the venv: rm -rf $VENV_DIR && $PYTHON -m venv $VENV_DIR"
    exit 2
fi
PYTHON="$VENV_DIR/bin/python"
dim "Using: $PYTHON ($("$PYTHON" --version))"

# ── Step 3: pip deps ────────────────────────────────────────────────────
step "Installing Python dependencies (gateway + whisper)..."
if $PIP install --quiet --upgrade pip; then
    dim "pip upgraded"
fi

REQ_FILES=("requirements-whisper.txt" "requirements-web.txt")
for req in "${REQ_FILES[@]}"; do
    if [[ ! -f "$SCRIPT_DIR/$req" ]]; then
        err "Missing $req in $SCRIPT_DIR — re-clone the repo?"
        exit 2
    fi
    dim "Installing $req..."
    if ! $PIP install -r "$SCRIPT_DIR/$req"; then
        err "pip install failed for $req"
        err "Check the error above. Common causes: no internet, conflicting system packages."
        exit 2
    fi
done

# ── Optional: client deps (split-architecture mode) ────────────────────
if [[ "$INSTALL_CLIENT" == "1" ]] || { [[ "$ASSUME_YES" == "0" ]] && ask "Also install the desktop voice client (sounddevice, websockets)?"; }; then
    if [[ -f "$SCRIPT_DIR/requirements-client.txt" ]]; then
        dim "Installing requirements-client.txt..."
        $PIP install -r "$SCRIPT_DIR/requirements-client.txt" || warn "Client deps failed (you can run this again later)"
    fi
    INSTALL_CLIENT=1
else
    INSTALL_CLIENT=0
    dim "Skipped client deps (use --with-client to install later)"
fi

# ── Step 4: ctranslate2 sanity check ────────────────────────────────────
step "Checking ctranslate2 version (4.7.2+ required for RTX 40/50)..."
CT_VER=$("$PYTHON" -c "import ctranslate2; print(ctranslate2.__version__)" 2>/dev/null || echo "0.0.0")
CT_MAJOR=$(echo "$CT_VER" | cut -d. -f1)
CT_MINOR=$(echo "$CT_VER" | cut -d. -f2)
if [[ "$CT_MAJOR" -lt 4 ]] || { [[ "$CT_MAJOR" -eq 4 ]] && [[ "$CT_MINOR" -lt 7 ]]; }; then
    warn "ctranslate2 $CT_VER is too old for modern NVIDIA GPUs (RTX 40/50 / Blackwell)."
    warn "Whisper will run ~10x slower than it should until you upgrade."
    if ask "Upgrade ctranslate2 to latest?"; then
        $PIP install --upgrade ctranslate2
    fi
else
    dim "ctranslate2 $CT_VER — OK"
fi

# ── Step 5: Whisper reachability ────────────────────────────────────────
step "Probing Whisper at http://127.0.0.1:$WHISPER_PORT ..."
WHISPER_REACHABLE=0
if curl -sf -m 2 "http://127.0.0.1:$WHISPER_PORT/health" >/dev/null 2>&1; then
    dim "Whisper is already running on :$WHISPER_PORT"
    WHISPER_REACHABLE=1
elif curl -sf -m 2 "http://127.0.0.1:$WHISPER_PORT/v1/audio/transcriptions" -X POST >/dev/null 2>&1; then
    # Some whisper servers don't have /health — POST probe to confirm
    dim "Whisper appears reachable on :$WHISPER_PORT (POST probe)"
    WHISPER_REACHABLE=1
fi

if [[ "$WHISPER_REACHABLE" == "0" ]]; then
    warn "Whisper not reachable on :$WHISPER_PORT"
    if [[ -f "$SCRIPT_DIR/whisper-server/server.py" ]]; then
        if ask "Install + start whisper-server now (uses faster-whisper, model=$WHISPER_MODEL)?"; then
            step "Starting whisper-server in the background..."
            nohup env WHISPER_PORT="$WHISPER_PORT" WHISPER_MODEL="$WHISPER_MODEL" \
                "$PYTHON" "$SCRIPT_DIR/whisper-server/server.py" \
                > /tmp/whisper.log 2>&1 &
            dim "Whisper PID: $!, log: /tmp/whisper.log"

            # Wait for it to come up
            for i in {1..60}; do
                if curl -sf -m 2 "http://127.0.0.1:$WHISPER_PORT/health" >/dev/null 2>&1; then
                    dim "Whisper ready after ${i}s"
                    WHISPER_REACHABLE=1
                    break
                fi
                sleep 1
            done
            if [[ "$WHISPER_REACHABLE" == "0" ]]; then
                warn "Whisper did not respond after 60s — check /tmp/whisper.log"
            fi
        fi
    else
        err "whisper-server/server.py not found in $SCRIPT_DIR"
        err "Set WHISPER_URL in .env to point at an existing Whisper server."
    fi
else
    dim "Whisper reachable — no action needed"
fi

# ── Step 6: .env config ────────────────────────────────────────────────
step "Configuring .env..."
ENV_FILE="$SCRIPT_DIR/.env"
ENV_EXAMPLE="$SCRIPT_DIR/.env.example"
if [[ ! -f "$ENV_FILE" && -f "$ENV_EXAMPLE" ]]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    dim "Created .env from .env.example"
fi
if [[ -f "$ENV_FILE" ]]; then
    if grep -qE "^WHISPER_URL=" "$ENV_FILE"; then
        dim "WHISPER_URL already set in .env"
    else
        echo "WHISPER_URL=http://127.0.0.1:$WHISPER_PORT/v1/audio/transcriptions" >> "$ENV_FILE"
        dim "Added WHISPER_URL=http://127.0.0.1:$WHISPER_PORT/v1/audio/transcriptions"
    fi
    if grep -qE "GROQ_API_KEY=|DEEPSEEK_API_KEY=|OPENAI_API_KEY=" "$ENV_FILE"; then
        if grep -qE "GROQ_API_KEY=.*[^_]$|DEEPSEEK_API_KEY=.*[^_]$|OPENAI_API_KEY=.*[^_]$" "$ENV_FILE"; then
            dim "An LLM API key is already set in .env"
        else
            warn "No LLM API key set in .env yet."
            warn "Edit $ENV_FILE and set one of:"
            warn "  GROQ_API_KEY=...       (free tier: https://console.groq.com/keys)"
            warn "  DEEPSEEK_API_KEY=...   (cheap: https://platform.deepseek.com/)"
            warn "  OPENAI_API_KEY=...     (https://platform.openai.com/)"
        fi
    else
        warn "No LLM API key in .env — voice will respond 'no LLM configured' until you set one."
    fi
else
    err ".env.example not found — skipping .env setup"
fi

# ── Step 7: optional model pre-download ────────────────────────────────
if [[ "$DOWNLOAD_MODEL" == "1" ]] || { [[ "$ASSUME_YES" == "0" ]] && ask "Pre-download the Whisper model ($WHISPER_MODEL, ~1.5GB)?"; }; then
    step "Pre-downloading $WHISPER_MODEL ..."
    "$PYTHON" -c "
from faster_whisper import WhisperModel
import os
# Just import + download — no transcription, no audio processing
print('Downloading (or verifying cache)...')
m = WhisperModel(os.environ.get('WHISPER_MODEL', '$WHISPER_MODEL'), device='auto', compute_type='auto')
print('Model ready')
" 2>&1 | tail -3
    dim "Done. First real STT call will be fast."
fi

# ── Step 8: final smoke test ───────────────────────────────────────────
step "Smoke test — can the gateway import?"
if "$PYTHON" -c "from hermes_voice.gateway import app" 2>&1 | tail -5; then
    dim "Gateway imports cleanly"
else
    warn "Gateway import failed. Common causes:"
    warn "  - Missing system libs (libportaudio, etc.) — see README#prerequisites"
    warn "  - Python version mismatch"
    warn "Try: $PYTHON -c 'from hermes_voice.gateway import app'  # for full error"
fi

# ── Summary ─────────────────────────────────────────────────────────────
printf '\n\033[0;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m\n'
printf '\033[0;32m✓ hermes-voice bootstrap complete\033[0m\n'
printf '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n'
printf 'Next steps:\n'
printf '  source %s/bin/activate\n' "$VENV_DIR"
printf '  ./start-all.sh                 # starts Whisper + gateway\n'
printf '  open http://localhost:8989     # web UI\n\n'
printf '  # Or, if installed as a Hermes plugin:\n'
printf '  /hermes-voice start            # slash command from any chat\n\n'
printf 'Installed:\n'
printf '  • venv:     %s\n' "$VENV_DIR"
if [[ "$WHISPER_REACHABLE" == "1" ]]; then
    printf '  • whisper:  http://127.0.0.1:%s (running)\n' "$WHISPER_PORT"
else
    printf '  • whisper:  not running on :%s\n' "$WHISPER_PORT"
fi
if [[ "$INSTALL_CLIENT" == "1" ]]; then
    printf '  • client:   installed\n\n'
else
    printf '  • client:   not installed (use --with-client to add)\n\n'
fi
