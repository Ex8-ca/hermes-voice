#!/bin/bash
# Launch Hermes Voice web server with DeepSeek API key from Hermes .env
source /home/marc/.hermes/.env 2>/dev/null
cd /home/marc/hermes-voice
exec ./venv/bin/python -m uvicorn hermes_voice.gateway:app --host 0.0.0.0 --port 8989
