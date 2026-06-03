#!/usr/bin/env bash
# bootstrap-client.sh — install the hermes-voice Python client (mic side).
#
# Use this on the machine that CAPTURES the microphone (often a different
# box from the one running the gateway + Whisper GPU). Installs:
#   - Python venv (reused if present)
#   - sounddevice, numpy, websockets, miniaudio, python-dotenv
#   - .env with HERMES_VOICE_WS_HOST / HERMES_VOICE_WS_PORT / GROQ_API_KEY
#
# Does NOT install: Whisper, ctranslate2, fastapi, Edge TTS — those are
# gateway-side and live in requirements-whisper.txt / requirements-web.txt.
#
# Usage:
#   ./bootstrap-client.sh                     # prompts for gateway host/port
#   ./bootstrap-client.sh 192.168.1.3 7979    # non-interactive
#   curl -fsSL .../bootstrap-client.sh | bash   # one-liner install

set -euo pipefail

# --- Color helpers (fix bash single-quote escape bug) -------------------------
c_green=$(printf '\033[0;32m')
c_yellow=$(printf '\033[0;33m')
c_red=$(printf '\033[0;31m')
c_blue=$(printf '\033[0;34m')
c_reset=$(printf '\033[0m')
info()  { printf "${c_blue}[bootstrap]${c_reset} %s\n" "$*"; }
ok()    { printf "${c_green}[bootstrap]${c_reset} %s\n" "$*"; }
warn()  { printf "${c_yellow}[bootstrap]${c_reset} %s\n" "$*"; }
err()   { printf "${c_red}[bootstrap]${c_reset} %s\n" "$*" >&2; }
die()   { err "$*"; exit 1; }

# --- Find repo root (this script lives in the repo) ---------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
info "Repo root: $SCRIPT_DIR"

# --- Python 3.10+ check --------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    die "python3 not found. Install it (apt/dnf/brew) and re-run."
fi
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    die "Python 3.10+ required (you have $PY_VER)."
fi
ok "Python $PY_VER"

# --- Venv create / reuse (with broken-pip-shebang fallback) -------------------
VENV_DIR="${SCRIPT_DIR}/venv"
if [ ! -d "$VENV_DIR" ]; then
    info "Creating venv at $VENV_DIR"
    python3 -m venv "$VENV_DIR"
    ok "venv created"
else
    # Check the pip shebang isn't pointing at a defunct path
    if [ -f "$VENV_DIR/bin/pip" ]; then
        SHEBANG=$(head -1 "$VENV_DIR/bin/pip" 2>/dev/null || true)
        case "$SHEBANG" in
            "#!"*python*)
                if ! head -1 "$SHEBANG" | grep -q "^#!" 2>/dev/null; then
                    SHEBANG_PATH=$(echo "$SHEBANG" | sed 's/^#!//')
                    if [ ! -x "$SHEBANG_PATH" ]; then
                        warn "Existing venv's pip shebang points at $SHEBANG_PATH which no longer exists."
                        warn "Will install via 'python -m pip' instead."
                    fi
                fi
                ;;
        esac
    fi
    ok "Reusing existing venv at $VENV_DIR"
fi

# Activate (works in bash + zsh; harmless if already activated)
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# --- Install client requirements ---------------------------------------------
PIP_CMD="python -m pip"
info "Installing client requirements (this is small — no Whisper)..."
$PIP_CMD install --upgrade pip >/dev/null
$PIP_CMD install -r requirements-client.txt
ok "Client deps installed"

# --- .env --------------------------------------------------------------------
ENV_FILE="$SCRIPT_DIR/.env"
NEED_ENV=0
if [ ! -f "$ENV_FILE" ]; then
    NEED_ENV=1
else
    # Check the key vars are set to non-placeholder values
    for VAR in HERMES_VOICE_WS_HOST HERMES_VOICE_WS_PORT GROQ_API_KEY; do
        if ! grep -q "^${VAR}=" "$ENV_FILE" 2>/dev/null; then
            NEED_ENV=1
            break
        fi
        VAL=$(grep "^${VAR}=" "$ENV_FILE" | cut -d= -f2-)
        if [ -z "$VAL" ] || [ "$VAL" = "your-groq-api-key-here" ] || [ "$VAL" = "changeme" ]; then
            NEED_ENV=1
            break
        fi
    done
fi

if [ "$NEED_ENV" -eq 1 ]; then
    info "Need to (re)write .env with real values"

    # Default host/port from CLI args or env or placeholder
    if [ "$#" -ge 2 ]; then
        WS_HOST="$1"
        WS_PORT="$2"
    elif [ -n "${HERMES_VOICE_WS_HOST:-}" ] && [ -n "${HERMES_VOICE_WS_PORT:-}" ]; then
        WS_HOST="$HERMES_VOICE_WS_HOST"
        WS_PORT="$HERMES_VOICE_WS_PORT"
    else
        WS_HOST=""
        WS_PORT=""
    fi

    if [ -z "$WS_HOST" ]; then
        printf "${c_yellow}Gateway host?${c_reset} (e.g. 192.168.1.3 or pop-os.taila6e2e.ts.net): "
        read -r WS_HOST
        [ -z "$WS_HOST" ] && die "Gateway host is required."
    fi
    if [ -z "$WS_PORT" ]; then
        printf "${c_yellow}Gateway port?${c_reset} [7979]: "
        read -r WS_PORT
        WS_PORT="${WS_PORT:-7979}"
    fi

    printf "${c_yellow}Groq API key?${c_reset} (or Enter to skip — set in .env later): "
    read -r -s GROQ_KEY
    printf "\n"
    GROQ_KEY="${GROQ_KEY:-your-groq-api-key-here}"

    cat > "$ENV_FILE" <<EOF
# hermes-voice client config
HERMES_VOICE_WS_HOST=$WS_HOST
HERMES_VOICE_WS_PORT=$WS_PORT
GROQ_API_KEY=$GROQ_KEY
EOF
    chmod 600 "$ENV_FILE"
    ok ".env written (chmod 600 — contains secrets)"
else
    ok ".env already configured"
fi

# --- Smoke test ---------------------------------------------------------------
info "Smoke test: import the client module"
if ! python -c "import hermes_voice.client; print('OK')" 2>&1 | tail -1 | grep -q "^OK$"; then
    die "Import failed. Check the error above."
fi
ok "Client imports cleanly"

# --- Done ---------------------------------------------------------------------
cat <<EOF

${c_green}✓ bootstrap-client.sh complete${c_reset}

To run the voice client:
    source venv/bin/activate
    python -m hermes_voice.client

Targeting gateway at:
    ws://$(grep '^HERMES_VOICE_WS_HOST' .env | cut -d= -f2):$(grep '^HERMES_VOICE_WS_PORT' .env | cut -d= -f2)/ws

If the gateway is on a different machine, make sure port 7979 (or whatever
you set) is reachable from this client. 'nc -vz <host> <port>' is a good
first check.
EOF
