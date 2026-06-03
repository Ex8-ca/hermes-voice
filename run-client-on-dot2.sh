#!/bin/bash
# Run hermes-voice-client on .2 with the correct audio devices
# Input device 5 = ALC269VC Analog combo jack mic (we unmuted this)
# Input device 7 = pipewire default (BH-M9 Pro BT mic if it's the default source)
# Output device 5 = ALC269VC Analog (wired speaker)
# Output device 7 = pipewire default (BH-M9 Pro BT speaker)
set -e
source ~/hermes-voice-client/venv/bin/activate
export HERMES_WS_HOST="192.168.1.3"
export HERMES_WS_PORT="7979"   # was 8989, now taken by audioforge
export HERMES_INPUT_DEVICE="7"   # pipewire default - follows active BT mic
export HERMES_OUTPUT_DEVICE="7"  # pipewire default - follows active BT speaker

# Choose log level from arg or env. Default INFO — much more readable than DEBUG.
# Usage:
#   ./run-client-on-dot2.sh          # INFO, scroll with Shift+PgUp or pipe to less
#   ./run-client-on-dot2.sh DEBUG    # full debug (very chatty, hard to follow)
#   ./run-client-on-dot2.sh | tee /tmp/voice.log   # live + saved log
LEVEL="${1:-${HERMES_LOG_LEVEL:-INFO}}"
export HERMES_LOG_LEVEL="$LEVEL"

LOG_FILE="/tmp/hermes-voice-client-$(date +%Y%m%d-%H%M%S).log"
echo "Starting hermes-voice-client on .2 (log level: $LEVEL)"
echo "  Gateway:   ws://$HERMES_WS_HOST:$HERMES_WS_PORT"
echo "  Mic:       device $HERMES_INPUT_DEVICE (pipewire default)"
echo "  Speaker:   device $HERMES_OUTPUT_DEVICE (pipewire default)"
echo "  Log file:  $LOG_FILE"
echo "  Tip: scroll up with Shift+PgUp / Shift+PgDn. Ctrl+C to quit."
echo "  Tip: re-run with:  ./run-client-on-dot2.sh DEBUG    for verbose"
echo "----- (output below, also saved to $LOG_FILE) -----"
echo

# Pipe through tee so you can read the live output AND have a saved log
exec hermes-voice-client 2>&1 | tee -a "$LOG_FILE"
