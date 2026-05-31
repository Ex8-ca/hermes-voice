#!/bin/bash
# Setup script for JARVIS Voice Shell on Ubuntu/Debian Linux.
# Run as: bash setup-linux.sh

set -e

echo "Setting up JARVIS Voice Shell on Linux..."

# System dependencies
echo "[1/4] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3 python3-pip python3-venv \
    portaudio19-dev \
    ffmpeg \
    libsndfile1 \
    2>/dev/null || {
        echo "⚠ apt install failed — try running manually:"
        echo "   sudo apt install python3 python3-pip python3-venv portaudio19-dev ffmpeg libsndfile1"
    }

# Create virtual environment
echo "[2/4] Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install JARVIS Voice Shell with all extras
echo "[3/4] Installing JARVIS Voice Shell..."
pip install -e ".[dev,stt,audio]"

# Download whisper model
echo "[4/4] Pre-downloading whisper tiny model..."
python3 -c "
import whisper
model = whisper.load_model('tiny')
print('✓ Whisper tiny model loaded')
"

echo ""
echo "Setup complete!"
echo ""
echo "To configure:"
echo "  1. cp .env.example .env"
echo "  2. Edit .env with your Hermes API key and bridge URL"
echo "  3. Run: bash start-jarvis-linux.sh"
