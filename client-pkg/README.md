# hermes-voice-client

Standalone Python client for the [hermes-voice](https://github.com/Ex8-ca/hermes-voice) gateway.

Captures your mic on **any** machine, streams raw PCM to a hermes-voice gateway running on your LAN, and plays back TTS audio. No browser, no plugin, no WebRTC — just a Python process.

## Install

```bash
pip install hermes-voice-client
```

For system audio support, install PortAudio + PipeWire:

```bash
# Debian / Ubuntu
sudo apt install libportaudio2 pipewire pipewire-pulse wireplumber

# Fedora
sudo dnf install portaudio pipewire pipewire-pulseaudio wireplumber

# Arch
sudo pacman -S portaudio pipewire pipewire-pulse wireplumber
```

## Run

```bash
# Defaults: connect to hermes-voice at 192.168.1.3:8989
hermes-voice-client

# Or with overrides
HERMES_WS_HOST=192.168.1.3 HERMES_WS_PORT=8989 hermes-voice-client
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `HERMES_WS_HOST` | `192.168.1.3` | Gateway hostname/IP |
| `HERMES_WS_PORT` | `8989` | Gateway WebSocket port |
| `HERMES_INPUT_DEVICE` | *(auto)* | Mic device index |
| `HERMES_OUTPUT_DEVICE` | *(auto)* | Speaker device index |
| `HERMES_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` |

## Find audio device indices

```bash
python3 -c "import sounddevice; print(sounddevice.query_devices())"
```

Then use the index number for `HERMES_INPUT_DEVICE` / `HERMES_OUTPUT_DEVICE`.

## How it works

```
┌──────────────────┐         WebSocket          ┌────────────────────┐
│  Client (.2)     │  raw PCM Int16 → gateway   │  Gateway (.3)      │
│                  │                            │                    │
│  sounddevice mic │  ws://.3:8989/ws           │  EnergyVAD         │
│       ↓          │ ← MP3 chunks (TTS)         │  Whisper STT       │
│  miniaudio       │                            │  DeepSeek LLM      │
│  speaker         │                            │  Edge TTS          │
└──────────────────┘                            └────────────────────┘
```

The client is intentionally minimal — all the heavy lifting (VAD, STT, LLM, TTS) happens on the gateway machine where the GPU lives.

## License

MIT — same as the gateway.
