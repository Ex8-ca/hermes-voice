#!/bin/bash
# Install hermes-voice-client on a remote host
# Usage: ./install-hermes-voice-client.sh user@host
set -e

REMOTE="$1"
if [ -z "$REMOTE" ]; then
    echo "Usage: $0 user@host"
    exit 1
fi

# Find the local wheel
WHEEL=$(ls -t /home/marc/Documents/myproj/hermes-voice/client-pkg/dist/hermes_voice_client-*.whl 2>/dev/null | head -1)
if [ -z "$WHEEL" ]; then
    echo "No wheel found. Run: cd /home/marc/Documents/myproj/hermes-voice/client-pkg && python3 -m build"
    exit 1
fi

echo "Using wheel: $WHEEL"
echo "Installing on $REMOTE..."

ssh -o IdentitiesOnly=yes -i ~/.ssh/hermes_ai5080 "$REMOTE" "
    set -e
    mkdir -p ~/hermes-voice-client
    python3 -m venv ~/hermes-voice-client/venv
    source ~/hermes-voice-client/venv/bin/activate
    pip install --quiet --upgrade pip
    pip install --quiet $WHEEL
    echo 'Installed. Run with:'
    echo '  ~/hermes-voice-client/venv/bin/hermes-voice-client'
"

echo "Done."
