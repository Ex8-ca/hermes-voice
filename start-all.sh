#!/bin/bash
# Start JARVIS voice web + Whisper STT server together
set -e

# Load .env if present
if [ -f .env ]; then
    set -a
    . .env
    set +a
fi

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Use venv if it exists, otherwise python3
if [ -d venv ]; then
    PYTHON="$SCRIPT_DIR/venv/bin/python"
else
    PYTHON=python3
fi

# Whisper STT server
echo "Starting Whisper STT server on :9001..."
WHISPER_MODEL=${WHISPER_MODEL:-turbo} $PYTHON whisper-server/server.py &
WHISPER_PID=$!
trap "kill $WHISPER_PID 2>/dev/null" EXIT

# Wait for Whisper to be ready
for i in {1..30}; do
    if curl -sf http://127.0.0.1:9001/health > /dev/null 2>&1; then
        echo "Whisper ready."
        break
    fi
    sleep 1
done

# JARVIS web server
echo "Starting JARVIS web server on :8989..."
exec $PYTHON -m uvicorn web.jarvis_web:app --host 0.0.0.0 --port 8989
