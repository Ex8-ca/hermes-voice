"""
Energy-based Voice Activity Detection (VAD) for the hermes-voice plugin.

Detects speech by measuring RMS amplitude of int16 PCM frames against a threshold.
States: idle → primed → speaking. Returns completed speech segments when sustained
silence is detected after speech.

This is a simple, CPU-cheap VAD. It works well for:
- Browser audio (echoCancellation + noiseSuppression + autoGainControl applied)
- Desktop mic with noise suppression enabled
- Voice UI where the speaker is in a quiet room

It does NOT work well for:
- High-noise environments (use Silero VAD instead)
- Far-field mics (use Silero or a neural VAD)
- Multiple simultaneous speakers

The algorithm:
- `energy_threshold` (default 300): RMS amplitude needed to count as "loud"
- `start_frames` (default 3): consecutive loud frames before transitioning PRIMED → SPEAKING
- `end_silence_frames` (default 11): consecutive quiet frames before ending SPEAKING
- `pre_roll_frames` (default 5): frames of audio retained before speech start (so initial
  consonants like "f", "s", "th" don't get clipped)

Tuning notes:
- If the AI never hears you, lower `energy_threshold` (try 150-200)
- If the AI hears phantom speech, raise `energy_threshold` (try 500-700)
- Browser audio (with echo cancellation etc.) tends to be quieter than raw mic,
  so values around 200-400 are typical.
"""
import math
from enum import Enum
from typing import Optional


class VADState(str, Enum):
    IDLE = "idle"
    PRIMED = "primed"
    SPEAKING = "speaking"


def rms_int16(frame: bytes) -> int:
    """Return the RMS amplitude of an int16 little-endian PCM frame.

    Returns 0 for empty input. Result is in the same units as int16 samples
    (0 to 32767).
    """
    if not frame:
        return 0
    sample_count = len(frame) // 2
    if sample_count <= 0:
        return 0
    total = 0
    for i in range(0, sample_count * 2, 2):
        sample = int.from_bytes(frame[i:i + 2], "little", signed=True)
        total += sample * sample
    return int(math.sqrt(total / sample_count))


class EnergyVAD:
    """Stateful energy-based VAD. Feed it PCM frames, get back completed segments."""

    def __init__(
        self,
        energy_threshold: int = 300,
        start_frames: int = 3,
        end_silence_frames: int = 11,
        pre_roll_frames: int = 5,
        sample_width: int = 2,  # bytes per sample (int16)
        frame_ms: int = 63,     # ms per chunk from the browser
    ):
        self.energy_threshold = int(energy_threshold)
        self.start_frames = max(1, int(start_frames))
        self.end_silence_frames = max(1, int(end_silence_frames))
        self.pre_roll_frames = max(0, int(pre_roll_frames))
        self.sample_width = int(sample_width)
        # samples per chunk (e.g. 1008 @ 63ms at 16kHz)
        self.samples_per_frame = 16000 * frame_ms // 1000
        self.state = VADState.IDLE
        self._pre_roll: list[bytes] = []
        self._primed: list[bytes] = []
        self._segment: list[bytes] = []
        self._loud_count = 0
        self._quiet_count = 0

    def _frame_rms(self, frame: bytes) -> int:
        return rms_int16(frame)

    def process(self, frame: bytes) -> Optional[bytes]:
        """Feed a PCM frame. Returns a complete speech segment (bytes) if the
        user just finished speaking, otherwise None.
        """
        loud = self._frame_rms(frame) >= self.energy_threshold

        if self.state == VADState.IDLE:
            if loud:
                self.state = VADState.PRIMED
                self._primed = [frame]
                self._loud_count = 1
            else:
                # Keep recent frames for pre-roll
                if self.pre_roll_frames > 0:
                    self._pre_roll.append(frame)
                    over = len(self._pre_roll) - self.pre_roll_frames
                    if over > 0:
                        self._pre_roll = self._pre_roll[over:]
            return None

        if self.state == VADState.PRIMED:
            if loud:
                self._primed.append(frame)
                self._loud_count += 1
                if self._loud_count >= self.start_frames:
                    self.state = VADState.SPEAKING
                    self._segment = list(self._pre_roll) + self._primed
                    self._quiet_count = 0
                    self._pre_roll = []
                    self._primed = []
            else:
                # quiet frame in PRIMED — reset
                self._pre_roll.extend(self._primed)
                self._pre_roll.append(frame)
                over = len(self._pre_roll) - self.pre_roll_frames
                if over > 0:
                    self._pre_roll = self._pre_roll[over:]
                self._primed = []
                self._loud_count = 0
                self.state = VADState.IDLE
            return None

        # SPEAKING state
        self._segment.append(frame)
        if loud:
            self._quiet_count = 0
            return None
        self._quiet_count += 1
        if self._quiet_count >= self.end_silence_frames:
            segment = b"".join(self._segment)
            self.reset()
            return segment
        return None

    def reset(self) -> None:
        self.state = VADState.IDLE
        self._pre_roll = []
        self._primed = []
        self._segment = []
        self._loud_count = 0
        self._quiet_count = 0
