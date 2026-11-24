from __future__ import annotations

from clipper.config import DetectionSettings
from clipper.detect.story import StoryWindow, TranscriptLine, _segments_from_windows


def make_window(start: float, end: float, kind: str, score: float, summary: str = "") -> StoryWindow:
    return StoryWindow(
        start=start,
        end=end,
        transcript="",
        audio_label="high",
        visual={
            "interesting": score >= 0.55,
            "score": score,
            "kind": kind,
            "summary": summary or kind,
            "evidence": "",
        },
    )


def test_long_funny_exchange_is_kept() -> None:
    windows = [
        make_window(0, 15, "filler", 0.1),
        make_window(15, 30, "funny", 0.8),
        make_window(30, 45, "banter", 0.8),
        make_window(45, 60, "filler", 0.1),
    ]
    lines = [
        TranscriptLine(16, 28, "bro that was fucking hilarious"),
        TranscriptLine(30, 44, "you cannot say that"),
    ]
    clips = _segments_from_windows(
        windows,
        lines,
        60,
        DetectionSettings(ai=True, ai_mode="director"),
    )
    assert len(clips) == 1
    assert clips[0].start <= 16
    assert clips[0].end >= 44
    assert clips[0].duration > 20


def test_tactical_callouts_are_not_sold_as_funny() -> None:
    windows = [
        make_window(0, 15, "funny", 0.8),
        make_window(15, 30, "funny", 0.8),
    ]
    lines = [
        TranscriptLine(1, 4, "Enemy remaining."),
        TranscriptLine(16, 20, "I should have my place B."),
    ]
    clips = _segments_from_windows(
        windows,
        lines,
        30,
        DetectionSettings(ai=True, ai_mode="director"),
    )
    assert clips == []


def test_gameplay_windows_survive_without_transcript() -> None:
    windows = [
        make_window(30, 45, "clutch", 0.9, "clutch defuse"),
        make_window(45, 60, "filler", 0.1),
    ]
    clips = _segments_from_windows(
        windows,
        [],
        60,
        DetectionSettings(ai=True, ai_mode="director"),
    )
    assert len(clips) == 1
    assert clips[0].start == 30
    assert clips[0].end == 45
