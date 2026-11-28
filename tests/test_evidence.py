from __future__ import annotations

import json
from pathlib import Path

from clipper.config import DetectionSettings
from clipper.detect.hud import HudLine, HudReading
from clipper.detect.signals import WindowSignal
from clipper.detect.story import (
    StoryWindow,
    TranscriptLine,
    _merge,
    _segments_from_windows,
)
from clipper.models import AnalysisSummary, ClipWindow, FileAnalysis, MediaInfo


def test_director_clip_records_grounded_evidence() -> None:
    settings = DetectionSettings(
        ai=True,
        ai_model="lfm3-omni",
        ai_game="Valorant",
        ai_min_confidence=0.5,
    )
    lines = [
        TranscriptLine(2.0, 3.0, "no way", "LAUGH"),
        TranscriptLine(3.2, 4.0, "that was insane", ""),
    ]
    window = StoryWindow(
        start=0.0,
        end=15.0,
        transcript="no way / that was insane",
        audio_label="high",
        visual={
            "interesting": True,
            "score": 0.92,
            "kind": "round",
            "summary": "the round ends with a reaction",
            "evidence": "VICTORY banner is visible",
        },
        signals=WindowSignal(
            start=0.0,
            end=15.0,
            laugh=0.8,
            quote="no way",
            peak_time=3.0,
        ),
    )
    clips = _segments_from_windows(
        [window],
        lines,
        20.0,
        settings,
        audio=None,
        hud_reader=lambda _start, _end: HudReading(
            lines=[HudLine(5.0, "VICTORY")],
            available=True,
        ),
    )
    assert len(clips) == 1
    clip = clips[0]
    evidence = clip.evidence
    assert evidence["model"] == "lfm3-omni"
    assert evidence["game"] == "Valorant"
    assert evidence["kind"] == "round"
    assert evidence["confidence"] == 0.92
    assert evidence["director"] == "VICTORY banner is visible"
    assert evidence["transcript"][0]["text"] == "no way"
    assert evidence["transcript"][0]["tags"] == "LAUGH"
    assert evidence["hud"][0]["text"] == "VICTORY"
    assert evidence["signal"]["labels"] == ["LAUGH"]
    assert evidence["reviewed_windows"][0]["score"] == 0.92


def test_merge_keeps_evidence_from_both_clips() -> None:
    left = ClipWindow(
        start=0.0,
        end=5.0,
        peak=2.0,
        score=0.7,
        reason="left",
        tags=["funny"],
        evidence={"transcript": [{"start": 1.0, "text": "left line"}]},
    )
    right = ClipWindow(
        start=5.5,
        end=10.0,
        peak=7.0,
        score=0.8,
        reason="right",
        tags=["clutch"],
        evidence={"transcript": [{"start": 6.0, "text": "right line"}]},
    )
    merged = _merge([left, right])
    assert len(merged) == 1
    clip = merged[0]
    assert clip.score == 0.8
    assert clip.reason == "right"
    assert clip.tags == ["funny", "clutch"]
    assert len(clip.evidence["transcript"]) == 2
    assert clip.evidence["transcript"][0]["text"] == "left line"


def test_clip_metadata_survives_json_roundtrip(tmp_path: Path) -> None:
    source = tmp_path / "match.mp4"
    source.write_bytes(b"video")
    clip = ClipWindow(
        start=1.0,
        end=2.0,
        peak=1.5,
        score=0.8,
        reason="round",
        id="abc",
        keep=False,
        note="keep the reaction",
        tags=["funny", "to-post"],
        evidence={"transcript": [{"text": "no way"}]},
        exports=[{"path": "out.mp4", "preset": "shorts"}],
    )
    summary = AnalysisSummary(
        files=[
            FileAnalysis(
                path=str(source),
                name=source.name,
                info=MediaInfo(path=str(source), duration=10.0),
                clips=[clip],
            )
        ],
        input_path=str(tmp_path),
        scan_id="scan_1",
        created_at="2026-11-28T12:00:00+00:00",
        updated_at="2026-11-28T12:05:00+00:00",
    )
    payload = json.loads(json.dumps(summary.to_dict()))
    restored = AnalysisSummary.from_dict(payload)
    assert restored.scan_id == "scan_1"
    assert restored.created_at == "2026-11-28T12:00:00+00:00"
    restored_clip = restored.files[0].clips[0]
    assert restored_clip.id == "abc"
    assert restored_clip.keep is False
    assert restored_clip.note == "keep the reaction"
    assert restored_clip.tags == ["funny", "to-post"]
    assert restored_clip.evidence["transcript"][0]["text"] == "no way"
    assert restored_clip.exports[0]["preset"] == "shorts"
