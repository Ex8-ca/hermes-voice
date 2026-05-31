#!/bin/bash
# Start JARVIS Voice Shell in always-on VAD mode on Linux.
#
# Usage:
#   ./start-jarvis-linux.sh [device_index]
#
# If device_index is provided, it overrides the auto-detected microphone.
# Run `python -m jarvis_voice_shell.cli list-devices` to find device indices.

set -e

# Load .env if it exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Check if virtual environment exists
if [ -f venv/bin/activate ]; then
    source venv/bin/activate
else
    echo "⚠ No venv found. Creating one..."
    python3 -m venv venv
    source venv/bin/activate
    echo "Installing dependencies..."
    pip install -e ".[dev,stt]" audio 2>/dev/null || pip install -e ".[dev,stt]"
fi

# Install system dependencies check
if ! command -v ffmpeg &> /dev/null; then
    echo "⚠ ffmpeg not found. TTS audio conversion may fail."
    echo "   Install with: sudo apt install ffmpeg"
fi

# List available audio devices
echo "┌─────────────────────────────────────────────────────────┐"
echo "│ JARVIS Voice Shell — Always-On VAD Mode                  │"
echo "├─────────────────────────────────────────────────────────┤"
echo "│ Bridge: ${HERMES_BRIDGE_URL:-http://192.168.1.3:6789/v1/chat/completions}"
echo "│ TTS:    ${JARVIS_TTS_VOICE:-en-GB-RyanNeural}"
echo "│ STT:    whisper tiny"
echo "└─────────────────────────────────────────────────────────┘"

echo ""
echo "Available audio devices:"
python3 -c "
import sounddevice as sd
for i, d in enumerate(sd.query_devices()):
    inp = d['max_input_channels']
    out = d['max_output_channels']
    if inp > 0 or out > 0:
        marker = '🎤' if inp > 0 and out == 0 else '🔊' if out > 0 and inp == 0 else '🎤🔊'
        print(f'  {marker} [{i}] {d[\"name\"]} (in={inp}, out={out})')
"
echo ""

DEVICE_FLAG=""
if [ -n "$1" ]; then
    DEVICE_FLAG="--input-device $1"
    echo "Using input device: $1"
else
    echo "Auto-detecting microphone..."
fi

echo ""
echo "Starting JARVIS. Speak naturally — press Ctrl+C to exit."
echo ""

python -m jarvis_voice_shell.cli run \
    --input-mode always-on \
    --brain http \
    --sample-rate 16000 \
    --tts-rate +0% \
    --stt-engine whisper \
    --stt-model tiny \
    --max-record-seconds 8 \
    --vad-threshold 300 \
    --vad-end-silence-ms 700 \
    $DEVICE_FLAG
