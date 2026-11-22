from __future__ import annotations

from dataclasses import replace

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

from ..config import DetectionSettings
from ..models import ClipWindow
from .audio import ScoreTrack


def resample_track(track: ScoreTrack, grid: np.ndarray) -> np.ndarray:
    if track.times.size == 0 or track.scores.size == 0:
        return np.zeros_like(grid, dtype=np.float32)
    return np.interp(grid, track.times, track.scores, left=0.0, right=0.0).astype(np.float32)


def fuse_tracks(
    grid: np.ndarray,
    audio: np.ndarray,
    visual: np.ndarray,
    audio_weight: float = 0.6,
    visual_weight: float = 0.4,
) -> np.ndarray:
    total = max(1e-9, audio_weight + visual_weight)
    aw, vw = audio_weight / total, visual_weight / total
    merged = aw * audio + vw * visual
    # Reward moments where both detectors agree, without letting one dominate.
    merged = merged * (1.0 + 0.12 * np.minimum(audio, visual))
    merged = np.clip(merged, 0.0, 1.0)
    if grid.size >= 4:
        step = float(np.median(np.diff(grid))) or 0.25
        sigma = max(0.5, 0.5 / step)
        merged = gaussian_filter1d(merged, sigma=sigma, mode="nearest")
    # Keep the score absolute: a fused peak driven by both detectors should read
    # higher than a weak, single-signal peak. Do not rescale every video to 1.0.
    return np.clip(merged, 0.0, 1.0).astype(np.float32)


def merge_windows(
    windows: list[ClipWindow],
    merge_gap: float = 1.0,
    duration: float | None = None,
) -> list[ClipWindow]:
    """Merge overlapping/nearby windows; keep the strongest peak in each."""

    if not windows:
        return []
    ordered = sorted(windows, key=lambda w: (w.start, w.end))
    merged: list[ClipWindow] = []
    for window in ordered:
        start = max(0.0, window.start)
        end = window.end if duration is None else min(duration, window.end)
        if end <= start:
            continue
        current = replace(window, start=start, end=end)
        if not merged:
            merged.append(current)
            continue
        last = merged[-1]
        if current.start <= last.end + max(0.0, merge_gap):
            strongest = current if current.score >= last.score else last
            merged[-1] = replace(
                last,
                start=min(last.start, current.start),
                end=max(last.end, current.end),
                peak=strongest.peak,
                score=max(last.score, current.score),
                audio_score=strongest.audio_score,
                visual_score=strongest.visual_score,
                reason=strongest.reason,
            )
        else:
            merged.append(current)
    return merged


def _reason(audio: float, visual: float) -> str:
    if audio >= 0.55 and visual >= 0.55:
        return "audio + motion"
    if audio >= 0.55:
        return "audio spike"
    if visual >= 0.55:
        return "motion spike"
    return "combined signal"


def pick_peaks(
    grid: np.ndarray,
    score: np.ndarray,
    audio: np.ndarray,
    visual: np.ndarray,
    settings: DetectionSettings,
    duration: float,
) -> list[ClipWindow]:
    """Adaptive peak picking with smart padding and overlap merging."""

    if grid.size < 2 or score.size < 2 or float(score.max(initial=0.0)) <= 0.0:
        return []

    step = float(np.median(np.diff(grid))) or 0.25
    sample_rate = 1.0 / step
    percentile = 99.5 - 9.0 * float(settings.sensitivity)
    threshold = max(0.15, float(np.percentile(score, percentile)))
    distance = max(2, int(round(4.0 * sample_rate)))
    peaks, _ = find_peaks(score, height=threshold, distance=distance, prominence=0.04)

    if peaks.size == 0:
        candidate = int(np.argmax(score))
        if float(score[candidate]) >= max(0.18, threshold * 0.85):
            peaks = np.array([candidate], dtype=int)
        else:
            return []

    windows: list[ClipWindow] = []
    for index in peaks:
        peak_time = float(grid[index])
        start = max(0.0, peak_time - settings.pre)
        end = min(duration, peak_time + settings.post)
        if end - start < min(settings.min_clip, 1.0) and duration > settings.min_clip:
            continue
        if end <= start:
            continue
        windows.append(
            ClipWindow(
                start=start,
                end=end,
                peak=peak_time,
                score=float(score[index]),
                audio_score=float(audio[index]),
                visual_score=float(visual[index]),
                reason=_reason(float(audio[index]), float(visual[index])),
            )
        )

    merged = merge_windows(windows, merge_gap=settings.merge_gap, duration=duration)
    merged = [clip for clip in merged if clip.duration >= settings.min_clip]
    merged.sort(key=lambda clip: clip.score, reverse=True)
    merged = merged[: settings.max_clips]
    merged.sort(key=lambda clip: clip.start)
    return merged
