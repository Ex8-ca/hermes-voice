"""
Unit tests for jarvis_voice_client.py barge-in components.

Run from the repo root:
    python3 -m pytest tests/test_voice_client_bargein.py -v
or:
    python3 tests/test_voice_client_bargein.py
"""
import sys
import os
import time
import threading
import numpy as np

# Make the parent dir + the hermes-voice plugin dir importable
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)
# `hermes-voice/` is a directory inside the repo root, so we need to import
# it as a package. Add the repo root to sys.path so `hermes_voice` resolves.
# The plugin's __init__.py makes it a proper package.

# Skip if sounddevice isn't installed (e.g. CI on macOS without audio)
try:
    import sounddevice  # noqa
except ImportError:
    print("sounddevice not installed — skipping")
    sys.exit(0)

# Plugin refactor: client.py now lives inside the hermes-voice plugin directory.
# Support both the new location and the legacy repo-root location.
try:
    from hermes_voice.client import TTSRefBuffer, SIDETONE_DELAY_SAMPLES, BARGE_IN_RMS
except ImportError:
    # Back-compat: pre-plugin layout had jarvis_voice_client.py at the repo root.
    from jarvis_voice_client import TTSRefBuffer, SIDETONE_DELAY_SAMPLES, BARGE_IN_RMS


def test_tts_ref_buffer_fifo():
    """TTSRefBuffer should be a strict FIFO: read returns samples in append order."""
    buf = TTSRefBuffer(maxlen_samples=1000)
    arr1 = np.array([1, 2, 3, 4, 5], dtype=np.int16)
    arr2 = np.array([6, 7, 8, 9, 10], dtype=np.int16)
    buf.append(arr1)
    buf.append(arr2)

    assert buf.is_active
    out = buf.read(5)
    assert out is not None
    assert out.tolist() == [1, 2, 3, 4, 5]
    out2 = buf.read(5)
    assert out2.tolist() == [6, 7, 8, 9, 10]


def test_tts_ref_buffer_active_window():
    """is_active should be True for ~200ms after the last append, then False."""
    buf = TTSRefBuffer()
    arr = np.array([1, 2, 3], dtype=np.int16)
    buf.append(arr)
    assert buf.is_active

    # Read everything, then wait for the active window to expire
    buf.read(3)
    time.sleep(0.25)
    assert not buf.is_active


def test_tts_ref_buffer_partial_read():
    """read(n) with buffer smaller than n should pad with zeros."""
    buf = TTSRefBuffer()
    arr = np.array([10, 20, 30], dtype=np.int16)
    buf.append(arr)
    out = buf.read(6)
    assert out is not None
    assert out.tolist() == [10, 20, 30, 0, 0, 0]


def test_tts_ref_buffer_overflow_drops_oldest():
    """When maxlen is exceeded, the oldest samples are dropped (deque behavior)."""
    buf = TTSRefBuffer(maxlen_samples=5)
    buf.append(np.array([1, 2, 3, 4, 5, 6, 7], dtype=np.int16))
    # Should now contain [3, 4, 5, 6, 7]
    out = buf.read(5)
    assert out.tolist() == [3, 4, 5, 6, 7]


def test_tts_ref_buffer_clear():
    """clear() should drop all samples and set is_active=False."""
    buf = TTSRefBuffer()
    buf.append(np.array([1, 2, 3], dtype=np.int16))
    buf.read(3)  # drain
    # Even though is_active is True, clear should reset
    buf.append(np.array([10, 20], dtype=np.int16))
    buf.clear()
    assert not buf.is_active
    assert buf.read(1) is None


def test_sidetone_cancellation_math():
    """Simulate the cancellation: mic_with_ai = pure_mic + pure_ai.
    After subtraction (mic_with_ai - ai_ref), we should get pure_mic back.
    """
    # Pure user voice: a 200Hz tone at amplitude 5000
    sr = 16000
    duration_s = 0.5
    t = np.arange(int(sr * duration_s)) / sr
    pure_user = (5000 * np.sin(2 * np.pi * 200 * t)).astype(np.int16)

    # AI's voice: 300Hz tone at amplitude 3000, with 80ms delay (= SIDETONE_DELAY_SAMPLES)
    ai_pure = (3000 * np.sin(2 * np.pi * 300 * t)).astype(np.int16)
    ai_delayed = np.zeros_like(ai_pure)
    ai_delayed[SIDETONE_DELAY_SAMPLES:] = ai_pure[:-SIDETONE_DELAY_SAMPLES]

    # Mic receives: user + ai_delayed (both at full amplitude)
    mic_combined = pure_user.astype(np.int32) + ai_delayed.astype(np.int32)

    # Cancellation: subtract ai_delayed from mic_combined
    cleaned = mic_combined - ai_delayed.astype(np.int32)

    # After ~SIDETONE_DELAY_SAMPLES, the cleaned signal should be very close
    # to the pure user signal (the AI part was subtracted out)
    np.testing.assert_array_equal(
        cleaned[SIDETONE_DELAY_SAMPLES:].astype(np.int16),
        pure_user[SIDETONE_DELAY_SAMPLES:],
    )


def test_barge_in_threshold_consistency():
    """BARGE_IN_RMS should be high enough to avoid false-positives on
    ambient noise but low enough to catch deliberate speech."""
    # Typical ambient room noise RMS: 50-200
    # Normal conversational speech RMS: 2000-5000
    # A whispered "hey jarvis" might be: 800-1500
    assert BARGE_IN_RMS >= 400, "BARGE_IN_RMS too low — would trigger on ambient noise"
    assert BARGE_IN_RMS <= 2000, "BARGE_IN_RMS too high — would miss normal speech"


if __name__ == "__main__":
    test_tts_ref_buffer_fifo()
    print("✓ test_tts_ref_buffer_fifo")
    test_tts_ref_buffer_active_window()
    print("✓ test_tts_ref_buffer_active_window")
    test_tts_ref_buffer_partial_read()
    print("✓ test_tts_ref_buffer_partial_read")
    test_tts_ref_buffer_overflow_drops_oldest()
    print("✓ test_tts_ref_buffer_overflow_drops_oldest")
    test_tts_ref_buffer_clear()
    print("✓ test_tts_ref_buffer_clear")
    test_sidetone_cancellation_math()
    print("✓ test_sidetone_cancellation_math")
    test_barge_in_threshold_consistency()
    print("✓ test_barge_in_threshold_consistency")
    print("\nAll tests passed.")
