from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from clipper.config import DetectionSettings
from clipper.detect import story
from clipper.detect.hud import HudLine, HudReading
from clipper.detect.signals import WindowSignal
from clipper.detect.story import StoryWindow, TranscriptLine, _segments_from_windows


def make_window(
    start: float,
    end: float,
    kind: str,
    score: float,
    summary: str = "",
    evidence: str = "",
    signals: WindowSignal | None = None,
) -> StoryWindow:
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
            "evidence": evidence,
        },
        signals=signals,
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
    assert "you cannot say that" in clips[0].reason


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
        make_window(30, 45, "clutch", 0.9, "clutch defuse", "at 38s the WON banner appears"),
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
    assert "WON banner" in clips[0].reason


def test_vague_gameplay_claims_are_rejected() -> None:
    windows = [
        make_window(0, 15, "multikill", 0.9, "Player executes a quick multikill"),
        make_window(30, 45, "clutch", 0.9, "Player clutches the round"),
    ]
    clips = _segments_from_windows(
        windows,
        [],
        60,
        DetectionSettings(ai=True, ai_mode="director"),
    )
    assert clips == []


def test_hud_text_verifies_a_gameplay_event() -> None:
    windows = [make_window(0, 15, "round", 0.9, "Player wins the round")]

    def reader(_start: float, _end: float) -> HudReading:
        return HudReading(
            lines=[
                HudLine(12.0, "WON"),
                HudLine(12.1, "ENEMY TEAM ELIMINATED"),
            ],
            available=True,
        )

    clips = _segments_from_windows(
        windows,
        [],
        15,
        DetectionSettings(ai=True, ai_mode="director"),
        hud_reader=reader,
    )
    assert len(clips) == 1
    assert "WON" in clips[0].reason
    assert "ENEMY TEAM ELIMINATED" in clips[0].reason


def test_hud_promotes_generic_gameplay_to_a_round() -> None:
    windows = [
        make_window(
            0,
            15,
            "gameplay",
            0.8,
            "Player wins the round",
            "88.8s - WON, SPIKE DEFUSED",
        )
    ]

    def reader(_start: float, _end: float) -> HudReading:
        return HudReading(
            lines=[HudLine(12.0, "WON"), HudLine(12.1, "ENEMY TEAM ELIMINATED")],
            available=True,
        )

    clips = _segments_from_windows(
        windows,
        [],
        15,
        DetectionSettings(ai=True, ai_mode="director"),
        hud_reader=reader,
    )
    assert len(clips) == 1
    assert clips[0].reason.startswith("AI round (HUD):")
    assert "WON" in clips[0].reason


def test_hud_rejects_a_hallucinated_banner() -> None:
    windows = [
        make_window(
            0,
            15,
            "round",
            0.9,
            "Player wins the round",
            "The WON banner appears at 12s",
        )
    ]

    def reader(_start: float, _end: float) -> HudReading:
        return HudReading(
            lines=[HudLine(4.0, "SPIKE"), HudLine(8.0, "MARSHAL")],
            available=True,
        )

    clips = _segments_from_windows(
        windows,
        [],
        15,
        DetectionSettings(ai=True, ai_mode="director"),
        hud_reader=reader,
    )
    assert clips == []


def test_chat_cue_keeps_banter_without_voice() -> None:
    windows = [make_window(0, 15, "banter", 0.8, "Team joking in chat")]

    def reader(_start: float, _end: float) -> HudReading:
        return HudReading(lines=[HudLine(6.0, "(Team) Tea: lol")], available=True)

    clips = _segments_from_windows(
        windows,
        [],
        15,
        DetectionSettings(ai=True, ai_mode="director"),
        hud_reader=reader,
    )
    assert len(clips) == 1
    assert "lol" in clips[0].reason


def test_long_banter_is_capped_around_the_payoff() -> None:
    windows = [make_window(start, start + 15, "banter", 0.8) for start in range(0, 90, 15)]
    lines = [
        TranscriptLine(start + 2, start + 8, "bro that was hilarious")
        for start in range(0, 90, 15)
    ]
    clips = _segments_from_windows(
        windows,
        lines,
        90,
        DetectionSettings(ai=True, ai_mode="director"),
    )
    assert len(clips) == 1
    assert clips[0].duration <= 45.1
    assert clips[0].duration >= 20
    assert "hilarious" in clips[0].reason


def test_hype_accepts_laugh_and_jerk_without_words() -> None:
    signal = WindowSignal(
        start=0,
        end=15,
        laugh=0.84,
        jerk=0.92,
        peak_time=7.0,
    )
    windows = [make_window(0, 15, "hype", 0.8, signals=signal)]
    clips = _segments_from_windows(
        windows,
        [],
        15,
        DetectionSettings(ai=True, ai_mode="director"),
    )
    assert len(clips) == 1
    assert clips[0].reason == "AI hype: [laugh 0.84, jerk 0.92]"


def test_hype_rejects_one_signal() -> None:
    signal = WindowSignal(start=0, end=15, laugh=0.84, peak_time=7.0)
    windows = [make_window(0, 15, "hype", 0.8, signals=signal)]
    clips = _segments_from_windows(
        windows,
        [],
        15,
        DetectionSettings(ai=True, ai_mode="director"),
    )
    assert clips == []


def test_signal_strong_funny_becomes_hype() -> None:
    signal = WindowSignal(
        start=0,
        end=15,
        laugh=0.80,
        jerk=0.90,
        quote="lets go go go run run",
        quote_start=6.0,
        quote_end=8.0,
        peak_time=7.0,
    )
    windows = [make_window(0, 15, "funny", 0.8, signals=signal)]
    clips = _segments_from_windows(
        windows,
        [],
        15,
        DetectionSettings(ai=True, ai_mode="director"),
    )
    assert len(clips) == 1
    assert clips[0].reason.startswith("AI hype:")
    assert "run run" in clips[0].reason
    assert "laugh" in clips[0].reason

def test_transcribe_uses_bundled_model_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundled = tmp_path / "base.en"
    bundled.mkdir()
    (bundled / "model.bin").write_bytes(b"model")
    captured: dict[str, object] = {}

    class FakeWhisperModel:
        def __init__(self, model, **kwargs) -> None:
            captured["model"] = model
            captured.update(kwargs)

        def transcribe(self, *args, **kwargs):
            return [], None

    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = FakeWhisperModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    monkeypatch.setattr(story, "BUNDLED_WHISPER", bundled)

    assert story.transcribe_audio(tmp_path / "audio.wav") == []
    assert captured["model"] == str(bundled)
    assert captured["local_files_only"] is True


def test_transcribe_falls_back_to_named_model_without_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    class FakeWhisperModel:
        def __init__(self, model, **kwargs) -> None:
            captured["model"] = model
            captured.update(kwargs)

        def transcribe(self, *args, **kwargs):
            return [], None

    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = FakeWhisperModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    monkeypatch.setattr(story, "BUNDLED_WHISPER", tmp_path / "missing")

    assert story.transcribe_audio(tmp_path / "audio.wav") == []
    assert captured["model"] == "base.en"
    assert captured["local_files_only"] is False
