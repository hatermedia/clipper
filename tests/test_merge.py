from __future__ import annotations

import numpy as np

from clipper.config import DetectionSettings
from clipper.detect.merge import fuse_tracks, merge_windows, pick_peaks
from clipper.models import ClipWindow


def make_clip(start: float, end: float, score: float = 0.5) -> ClipWindow:
    return ClipWindow(
        start=start,
        end=end,
        peak=(start + end) / 2,
        score=score,
        audio_score=score,
        visual_score=score,
        reason="test",
    )


def test_merge_overlapping_windows() -> None:
    merged = merge_windows([make_clip(10, 20, 0.6), make_clip(18, 25, 0.9)])
    assert len(merged) == 1
    assert merged[0].start == 10
    assert merged[0].end == 25
    assert merged[0].score == 0.9


def test_merge_gap_threshold() -> None:
    windows = [make_clip(10, 15), make_clip(17, 22)]
    assert len(merge_windows(windows, merge_gap=1.0)) == 2
    assert len(merge_windows(windows, merge_gap=3.0)) == 1


def test_merge_clamps_to_duration() -> None:
    merged = merge_windows([make_clip(-2, 5), make_clip(4, 99)], duration=50)
    assert merged[0].start == 0
    assert merged[0].end == 50


def test_merge_empty() -> None:
    assert merge_windows([]) == []


def test_fuse_tracks_rewards_agreement() -> None:
    grid = np.arange(0, 10, 0.25)
    audio = np.zeros_like(grid)
    visual = np.zeros_like(grid)
    audio[12:16] = 0.8
    visual[12:16] = 0.8
    fused = fuse_tracks(grid, audio, visual, 0.5, 0.5)
    audio_only = fuse_tracks(grid, audio, np.zeros_like(grid), 0.5, 0.5)
    assert fused.max() <= 1.0
    assert fused[14] > 0.5
    assert fused[14] > audio_only[14]


def test_pick_peaks_finds_two_known_moments() -> None:
    grid = np.arange(0, 60, 0.25)
    score = np.exp(-0.5 * ((grid - 20) / 1.0) ** 2) + np.exp(-0.5 * ((grid - 40) / 1.0) ** 2)
    score = (score / score.max()).astype(np.float32)
    audio = score.copy()
    visual = score.copy()
    settings = DetectionSettings(pre=3, post=3, sensitivity=0.5, min_clip=2, merge_gap=1)
    clips = pick_peaks(grid, score, audio, visual, settings, duration=60)
    assert len(clips) == 2
    assert clips[0].start < 20 < clips[0].end
    assert clips[1].start < 40 < clips[1].end
    assert all(clip.peak in (20.0, 40.0) for clip in clips)


def test_pick_peaks_respects_max_clips() -> None:
    grid = np.arange(0, 120, 0.25)
    score = np.zeros_like(grid)
    for centre in np.arange(5, 115, 10):
        score += np.exp(-0.5 * ((grid - centre) / 0.8) ** 2)
    score = (score / score.max()).astype(np.float32)
    settings = DetectionSettings(pre=1, post=1, sensitivity=1.0, min_clip=1, max_clips=3, merge_gap=0)
    clips = pick_peaks(grid, score, score, score, settings, duration=120)
    assert 1 <= len(clips) <= 3


def test_pick_peaks_flat_signal_returns_nothing() -> None:
    grid = np.arange(0, 30, 0.25)
    flat = np.zeros_like(grid, dtype=np.float32)
    settings = DetectionSettings()
    assert pick_peaks(grid, flat, flat, flat, settings, duration=30) == []
