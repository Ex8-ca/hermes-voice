#!/bin/bash
# install-hermes-voice-client.sh — set up the standalone voice client
# Run this on .2 (or any client machine) after copying hermes_voice_client.py here.
#
# Usage:
#   bash install-hermes-voice-client.sh
#
# What it does:
#   1. Creates a venv at ~/.venvs/hermes-voice
#   2. Installs sounddevice, numpy, websockets, miniaudio
#   3. Tests that the client can see the gateway at $HERMES_WS_HOST:$HERMES_WS_PORT

set -e

HERMES_WS_HOST="${HERMES_WS_HOST:-192.168.1.3}"
HERMES_WS_PORT="${HERMES_WS_PORT:-8989}"
VENV_DIR="${HOME}/.venvs/hermes-voice"
CLIENT_SCRIPT="$(dirname "$0")/hermes_voice_client.py"

if [ ! -f "$CLIENT_SCRIPT" ]; then
    echo "❌ $CLIENT_SCRIPT not found."
    echo "   Copy hermes_voice_client.py to the same directory as this script first."
    exit 1
fi

echo "→ Creating venv at $VENV_DIR"
python3 -m venv "$VENV_DIR" || {
    echo "❌ python3 -m venv failed. Try: sudo apt install python3-venv python3-full"
    exit 1
}

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "→ Upgrading pip"
pip install --quiet --upgrade pip wheel

echo "→ Installing deps (sounddevice, numpy, websockets, miniaudio)"
pip install --quiet sounddevice numpy websockets miniaudio

# System packages for sounddevice (PortAudio) and PipeWire integration
if command -v apt-get >/dev/null; then
    echo "→ Checking system audio packages"
    for pkg in libportaudio2 libpipewire-0.3-modules pipewire pipewire-pulse wireplumber; do
        if ! dpkg -s "$pkg" >/dev/null 2>&1; then
            echo "   ⚠️  $pkg not installed (may need: sudo apt install $pkg)"
        fi
    done
fi

# Quick reachability test
echo "→ Testing gateway at $HERMES_WS_HOST:$HERMES_WS_PORT"
if curl -s --max-time 3 "http://$HERMES_WS_HOST:$HERMES_WS_PORT/" >/dev/null; then
    echo "   ✓ Gateway reachable"
else
    echo "   ⚠️  Gateway not reachable. Make sure hermes_voice is running on $HERMES_WS_HOST"
fi

echo ""
echo "✓ Done. To start the voice client:"
echo ""
echo "    source $VENV_DIR/bin/activate"
echo "    HERMES_WS_HOST=$HERMES_WS_HOST HERMES_WS_PORT=$HERMES_WS_PORT \\"
echo "        python3 $CLIENT_SCRIPT"
echo ""
echo "  Or one-shot:"
echo ""
echo "    $VENV_DIR/bin/python3 $CLIENT_SCRIPT"
echo ""
echo "  If audio devices aren't auto-detected, override with HERMES_INPUT_DEVICE / HERMES_OUTPUT_DEVICE."
echo "  List devices with: $VENV_DIR/bin/python3 -c 'import sounddevice; print(sounddevice.query_devices())'"
