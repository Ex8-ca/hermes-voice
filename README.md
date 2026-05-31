# JARVIS Voice Shell

A persistent voice pipeline between a local client (`.150`) and a remote Hermes gateway (`.3`). The client captures audio, sends PCM frames over WebSocket to the gateway, receives TTS audio back, and plays it through the local speaker.

> JARVIS is used here as an assistant-style project name. This project is not affiliated with Marvel, Disney, OpenAI, Microsoft, or Nous Research.

## Architecture

```
[.150 — JARVIS Voice Client]          [.3 — JARVIS WS Gateway]
                                      /
Microphone (BT headset) ──► VAD ──► STT (Whisper) ──► LLM (Hermes) ──► TTS (Edge) ──► Speakers
                                   ▲                              │
                                   └──────────────────────────────┘
                                     Persistent WebSocket (port 6790)
```

The gateway runs on the same machine as Hermes Agent. The client runs on a separate machine (or the same machine locally). Only the WebSocket traffic crosses the network — audio capture, VAD, TTS playback, and PipeWire/BT audio routing all stay local on the client.

## Files

- `jarvis_voice_client.py` — Local client: mic capture, 44100→16kHz resampling, persistent WebSocket, TTS playback
- `jarvis_ws_gateway.py` — Remote gateway: VAD state machine, Whisper STT, Hermes LLM, Edge TTS streaming
- `systemd/jarvis-voice-client.service` — systemd user unit for persistent client on `.150`

## Configure

The client reads from `~/.env` (or environment variables):

```bash
JARVIS_WS_HOST=192.168.1.3
JARVIS_WS_PORT=6790
```

The gateway reads its API key from `~/.hermes/config.yaml` (the same key Hermes Agent uses). No separate `.env` needed for the gateway.

## Quick Start

### Gateway (`.3`)

```bash
# One-time: read API key from config and start the gateway
KEY=$(python3 -c "import yaml; print(__import__('yaml').safe_load(open('~/.hermes/config.yaml'))['model']['api_key'])")
nohup env HERMES_API_KEY="$KEY" ~/.hermes/hermes-agent/venv/bin/python /home/marc/jarvis_ws_gateway.py >> ~/.hermes/jarvis_ws_gateway.log 2>&1 &

# Verify
curl http://localhost:6790/health
```

Or use the restart script:
```bash
/tmp/restart_gateway.sh
```

The gateway requires:
- Hermes Agent running on port 6789 (provides the LLM `/v1/chat/completions` endpoint)
- Whisper STT service at `http://127.0.0.1:9001/v1/audio/transcriptions`
- Edge TTS in the Python environment

### Client (`.150`)

```bash
# Create venv and install dependencies
python -m venv ~/jarvis-voice-shell/venv
~/jarvis-voice-shell/venv/bin/pip install sounddevice numpy websockets miniaudio

# Copy client and configure
cp jarvis_voice_client.py ~/
cp systemd/jarvis-voice-client.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable jarvis-voice-client
systemctl --user start jarvis-voice-client

# Watch logs
journalctl --user -u jarvis-voice-client -f
```

Set BT headset as default audio source/sink:
```bash
pactl set-default-source bluez_input.41:42:FF:86:77:26
pactl set-default-sink bluez_output.41_42_FF_86_77_26.1
# Boost mic gain if needed (above 100% to compensate for BT headset quietness)
pactl set-source-volume bluez_input.41:42:FF:86:77:26 200000
```

## Audio Pipeline

| Stage | Location | Details |
|---|---|---|
| Mic capture | `.150` | sounddevice, PipeWire default (device 19), 44100Hz float32 |
| Resampling | `.150` | 44100 → 16000 Hz via numpy.interp, 2016 bytes/frame |
| VAD | `.3` | Energy-based VAD, threshold=20, pre_roll=3, end_silence=5 |
| STT | `.3` | faster-whisper at `localhost:9001`, model: tiny |
| LLM | `.3` | Hermes Gateway at `localhost:6789/v1/chat/completions`, Bearer auth |
| TTS | `.3` | Edge TTS, voice: en-GB-RyanNeural |
| Playback | `.150` | miniaudio MP3 decode → sounddevice OutputStream, 16kHz s16le |

VAD state machine: `idle → (loud frame) → speaking → (5 quiet frames) → segment → STT`

## No Wake Word

The client listens continuously — there is no wake word. VAD triggers on any sufficiently loud audio (RMS ≥ 20 at 16kHz). To add a wake word (e.g. "Hey Jarvis"), a Porcupine/Rhino module would need to be inserted between mic capture and the WebSocket send loop.

## Troubleshooting

```bash
# Check client is running
systemctl --user status jarvis-voice-client

# Check gateway is running
curl http://192.168.1.3:6790/health

# Restart client
systemctl --user restart jarvis-voice-client

# Restart gateway
/tmp/restart_gateway.sh

# Watch client logs
journalctl --user -u jarvis-voice-client -f

# Watch gateway logs
tail -f ~/.hermes/jarvis_ws_gateway.log

# Check BT headset volume (should be 200000+ for reliable VAD)
pactl list sources | grep -A5 bluez_input.41:42:FF:86:77:26

# List audio devices
python3 -c "import sounddevice as sd; [print(i, d['name'], 'in=', d['max_input_channels']) for i, d in enumerate(sd.query_devices())]"
```

## Security

- The client `.env` contains `JARVIS_WS_HOST` — do not commit it
- The gateway reads its LLM API key from `~/.hermes/config.yaml` — not passed as a file in this repo
- The `.git-credentials` file contains a GitHub PAT — never commit it

## Known Limitations

- BT headset mic (YYK-Q16) uses mSBC SCO codec which is low fidelity — transcription quality is lower than a wired headset or built-in mic
- `bluez5.loopback=true` in PipeWire for the BT source routes mic back to speaker — this is normal for headsets but limits recording quality
- No wake word — always-on VAD listens from the moment the client starts
- Gateway restart script is a temporary workaround — the gateway should eventually run as a systemd service on `.3`