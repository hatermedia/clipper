from __future__ import annotations

import numpy as np
from scipy.io import wavfile

from clipper.detect.audio import analyze_audio, analyze_wav


def make_signal(duration: float = 12.0, sample_rate: int = 16000) -> np.ndarray:
    times = np.arange(int(duration * sample_rate), dtype=np.float32) / sample_rate
    rng = np.random.default_rng(7)
    samples = rng.normal(0, 0.0008, times.size).astype(np.float32)
    burst = (times >= 4.0) & (times < 4.6)
    samples[burst] += 0.7 * np.sin(2 * np.pi * 440 * times[burst]).astype(np.float32)
    return samples


def test_audio_spike_is_detected() -> None:
    samples = make_signal()
    track = analyze_audio(samples, 16000)
    assert track.scores.size > 0
    assert float(track.scores.max()) > 0.4
    peak_time = float(track.times[int(np.argmax(track.scores))])
    assert 3.7 <= peak_time <= 5.0


def test_constant_tone_is_not_a_spike() -> None:
    sample_rate = 16000
    times = np.arange(sample_rate * 10, dtype=np.float32) / sample_rate
    tone = (0.3 * np.sin(2 * np.pi * 300 * times)).astype(np.float32)
    track = analyze_audio(tone, sample_rate)
    assert float(track.scores.max(initial=0.0)) < 0.15


def test_silence_is_not_a_spike() -> None:
    track = analyze_audio(np.zeros(16000 * 5, dtype=np.float32), 16000)
    assert float(track.scores.max(initial=0.0)) == 0.0


def test_analyze_wav_matches_in_memory(tmp_path) -> None:
    samples = make_signal()
    wav = tmp_path / "audio.wav"
    wavfile.write(wav, 16000, (samples * 32767).astype(np.int16))
    track = analyze_wav(wav)
    assert track.scores.size > 0
    assert 3.7 <= float(track.times[int(np.argmax(track.scores))]) <= 5.0
