#!/bin/bash
# Fix BT audio visibility on Pop!_OS / Ubuntu with PipeWire
# Run this on .2 (the client machine) if your Bluetooth headphones are paired
# but don't show up in sounddevice / PipeWire.

set -e

echo "=== Current state ==="
pgrep -a pipewire 2>&1 | head -3 || echo "no pipewire"
pgrep -a wireplumber 2>&1 | head -3 || echo "no wireplumber"
pgrep -a bluetoothd 2>&1 | head -3 || echo "no bluetoothd"

echo ""
echo "=== Is the BH-M9 Pro paired + connected? ==="
bluetoothctl devices Connected 2>&1 | head -5

echo ""
echo "=== wireplumber status (after running fix) ==="
sleep 1
wpctl status 2>&1 | head -30 || echo "wpctl not installed"

echo ""
echo "=== Make sure audio profile gets negotiated ==="
# Force the headphones to connect with audio profile
if [ -d /etc/wireplumber ]; then
    if [ ! -f /etc/wireplumber/bluetooth.lua.d/50-bluez-monitor.lua ]; then
        sudo mkdir -p /etc/wireplumber/bluetooth.lua.d
        sudo tee /etc/wireplumber/bluetooth.lua.d/50-bluez-monitor.lua > /dev/null <<'LUA'
bluez_monitor.properties = {
  ["bluez5.enable-sbc-xq"] = true,
  ["bluez5.enable-msbc"] = true,
  ["bluez5.enable-hw-volume"] = true,
  ["bluez5.codec"] = "mSBC",
}
LUA
        echo "Wrote bluez5 codec config"
    fi
fi

echo ""
echo "Restarting wireplumber + pipewire..."
systemctl --user restart wireplumber pipewire 2>&1 || true
sleep 2

echo ""
echo "=== After restart ==="
wpctl status 2>&1 | head -30 || true

echo ""
echo "=== Final: are BT devices in sounddevice now? ==="
~/hermes-voice/venv/bin/python3 -c "import sounddevice; [print(i, d.get('name')) for i, d in enumerate(sounddevice.query_devices()) if 'bluez' in d.get('name','').lower() or 'bh' in d.get('name','').lower() or 'avantree' in d.get('name','').lower()]"
