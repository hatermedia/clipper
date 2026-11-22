from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.ndimage import gaussian_filter1d, median_filter

HOP_SECONDS = 0.05
SILENCE_DB = -48.0


@dataclass
class ScoreTrack:
    times: np.ndarray
    scores: np.ndarray

    def __post_init__(self) -> None:
        self.times = np.asarray(self.times, dtype=np.float64)
        self.scores = np.asarray(self.scores, dtype=np.float32)

    @property
    def empty(self) -> bool:
        return self.times.size == 0 or float(self.scores.max(initial=0.0)) <= 0.0


def _to_mono_float(chunk: np.ndarray) -> np.ndarray:
    if chunk.ndim > 1:
        chunk = chunk.mean(axis=1)
    if chunk.dtype == np.uint8:
        return (chunk.astype(np.float32) - 128.0) / 128.0
    if chunk.dtype == np.int16:
        return chunk.astype(np.float32) / 32768.0
    if chunk.dtype == np.int32:
        return chunk.astype(np.float32) / 2147483648.0
    return chunk.astype(np.float32, copy=False)


def _rms_db_from_chunk(chunk: np.ndarray, frame: int) -> np.ndarray:
    usable = (chunk.size // frame) * frame
    if usable == 0:
        return np.empty(0, dtype=np.float32)
    blocks = _to_mono_float(chunk[:usable]).reshape(-1, frame)
    rms = np.sqrt(np.mean(blocks * blocks, axis=1) + 1e-12)
    return (20.0 * np.log10(rms + 1e-9)).astype(np.float32)


def _score_db(db: np.ndarray, hop: float) -> np.ndarray:
    if db.size < 8:
        return np.zeros_like(db, dtype=np.float32)
    if float(db.max()) < SILENCE_DB:
        return np.zeros_like(db, dtype=np.float32)

    # A 4-second rolling median is the "normal" loudness of this footage.
    window = max(3, int(round(4.0 / hop)))
    if window % 2 == 0:
        window += 1
    baseline = median_filter(db, size=window, mode="nearest")
    excess = np.clip(db - baseline, 0.0, None)

    centre = float(np.median(excess))
    mad = float(np.median(np.abs(excess - centre)))
    scale = max(1.5, 1.4826 * mad)
    novelty = np.clip((excess - centre) / scale / 3.5, 0.0, 1.0)

    p10, p95 = (float(v) for v in np.percentile(db, [10, 95]))
    absolute = np.clip((db - p10) / max(6.0, p95 - p10), 0.0, 1.0)

    score = 0.78 * novelty + 0.22 * absolute
    sigma = max(0.5, 0.6 / hop)
    score = gaussian_filter1d(score, sigma=sigma, mode="nearest")

    p99 = float(np.percentile(score, 99))
    if p99 < 0.08:
        return np.zeros_like(score, dtype=np.float32)
    return np.clip(score / max(p99, 1e-6), 0.0, 1.0).astype(np.float32)


def analyze_audio(samples: np.ndarray, sample_rate: int, hop: float = HOP_SECONDS) -> ScoreTrack:
    """Score an in-memory PCM signal for sudden loudness/RMS spikes."""

    if sample_rate <= 0:
        return ScoreTrack(np.array([]), np.array([]))
    frame = max(1, int(round(sample_rate * hop)))
    db = _rms_db_from_chunk(np.asarray(samples), frame)
    if db.size == 0:
        return ScoreTrack(np.array([]), np.array([]))
    times = (np.arange(db.size) + 0.5) * (frame / sample_rate)
    return ScoreTrack(times, _score_db(db, hop))


def analyze_wav(path: Path | str, hop: float = HOP_SECONDS) -> ScoreTrack:
    """Stream a 16-bit PCM WAV in chunks so multi-hour VODs stay memory-safe."""

    wav_path = Path(path)
    try:
        sample_rate, data = wavfile.read(str(wav_path), mmap=True)
    except (ValueError, TypeError):
        sample_rate, data = wavfile.read(str(wav_path))

    if sample_rate <= 0 or getattr(data, "size", 0) == 0:
        return ScoreTrack(np.array([]), np.array([]))

    frame = max(1, int(round(sample_rate * hop)))
    total_frames = int(data.shape[0]) // frame
    if total_frames == 0:
        return ScoreTrack(np.array([]), np.array([]))

    # ~4096 analysis windows per batch keeps peak memory in the low MBs.
    frames_per_chunk = 4096
    db = np.empty(total_frames, dtype=np.float32)
    for start in range(0, total_frames, frames_per_chunk):
        end = min(total_frames, start + frames_per_chunk)
        chunk = np.asarray(data[start * frame : end * frame])
        db[start:end] = _rms_db_from_chunk(chunk, frame)

    times = (np.arange(total_frames) + 0.5) * (frame / sample_rate)
    return ScoreTrack(times, _score_db(db, hop))
