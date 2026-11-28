from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from clipper.config import DetectionSettings
from clipper.detect import story
from clipper.detect.ears import AudioChunk, AudioReading
from clipper.detect.hud import HudLine, HudReading
from clipper.detect.signals import WindowSignal
from clipper.detect.story import (
    StoryWindow,
    TranscriptLine,
    _apply_audio_reading,
    _clean_model_text,
    _same_model,
    _segments_from_windows,
)
from clipper.models import ClipWindow


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


def test_director_reviews_every_window_of_the_full_clip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reviewed: list[tuple[float, float]] = []

    from clipper.gpu import GpuMemory

    monkeypatch.setattr(
        story,
        "query_nvidia_memory",
        lambda: GpuMemory(
            index=0,
            name="RTX 4090",
            uuid="GPU-0",
            total_mb=24564,
            used_mb=4096,
            free_mb=20468,
        ),
    )
    monkeypatch.setattr(story, "configure_runtime", lambda *args, **kwargs: "ollama")
    monkeypatch.setattr(story, "stop_runtime", lambda: None)
    monkeypatch.setattr(story, "model_available", lambda _model: True)
    monkeypatch.setattr(story, "transcribe_audio", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        story,
        "analyze_signals",
        lambda *args, **kwargs: types.SimpleNamespace(
            acoustic=types.SimpleNamespace(yamnet=True)
        ),
    )
    monkeypatch.setattr(story, "tag_transcript", lambda *args, **kwargs: None)
    monkeypatch.setattr(story, "window_signal", lambda *args, **kwargs: None)
    monkeypatch.setattr(story, "_segments_from_windows", lambda *args, **kwargs: [])

    def review(_video, window, _model, _bins, _game):
        reviewed.append((window.start, window.end))
        return {
            "interesting": False,
            "score": 0.0,
            "kind": "filler",
            "summary": "",
            "evidence": "",
        }

    monkeypatch.setattr(story, "_review_window", review)
    clips, warnings = story.direct_clip(
        tmp_path / "clip.mp4",
        60.0,
        DetectionSettings(ai=True, ai_mode="director"),
        None,
        None,
        None,
    )
    assert clips == []
    assert warnings
    assert reviewed[0][0] == pytest.approx(0.0)
    assert reviewed[-1][1] == pytest.approx(60.0)
    assert len(reviewed) >= 4
    assert all(end - start >= 1.0 for start, end in reviewed)
    assert all(
        reviewed[index + 1][0] < reviewed[index][1]
        for index in range(len(reviewed) - 1)
    )


def test_social_prompt_ignores_game_hud() -> None:
    prompt = story._window_prompt(make_window(0, 15, "filler", 0.0), "Social")
    assert "social/desktop" in prompt.lower()
    assert "ignore the gameplay category" in prompt.lower()
    assert "jokes, trolling" in prompt.lower()


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

def make_reading(
    start: float,
    end: float,
    *,
    score: float = 0.8,
    tone: str = "sarcastic",
    laughter: bool = True,
    trusted: bool = True,
    speech: str = "you fucking idiot",
) -> AudioReading:
    chunk = AudioChunk(
        start=start,
        end=end,
        speech=speech,
        tone=tone,
        laughter=laughter,
        shouting=False,
        sound="speech",
        proof=speech,
        score=score,
        trusted=trusted,
        overlap=1.0,
    )
    return AudioReading(
        chunks=(chunk,),
        score=score,
        peak=(start + end) / 2.0,
        reason=f'{"laughter + " if laughter else ""}"{speech}"',
        transcript=speech,
        trusted=trusted,
        laughter=laughter,
        tone=tone,
    )


def test_social_clip_tightens_around_the_heard_payoff() -> None:
    clip = ClipWindow(
        start=0.0,
        end=46.0,
        peak=23.0,
        score=0.8,
        reason='AI banter: "yeah bro no"',
    )
    reading = make_reading(38.0, 43.0)
    lines = [
        TranscriptLine(37.0, 39.0, "Yeah bro, no."),
        TranscriptLine(39.0, 43.0, "You fucking idiot!"),
    ]
    adjusted = _apply_audio_reading(
        clip, reading, lines, 60.0, "Social", 3.0
    )
    assert adjusted.start >= 8.0
    assert adjusted.end <= 46.0
    assert adjusted.duration <= 26.01
    assert adjusted.score > clip.score
    assert "heard" in adjusted.reason.lower()
    assert "idiot" in adjusted.reason.lower()


def test_gameplay_clip_extends_to_include_the_reaction() -> None:
    clip = ClipWindow(
        start=20.0,
        end=31.0,
        peak=25.0,
        score=0.85,
        reason="AI goal (HUD): GOAL",
    )
    reading = make_reading(28.0, 33.0, tone="excited", laughter=False)
    adjusted = _apply_audio_reading(
        clip, reading, [], 60.0, "Rocket League", 3.0
    )
    assert adjusted.start == clip.start
    assert adjusted.end > clip.end
    assert adjusted.end <= 50.0
    assert adjusted.score > clip.score


def test_low_affect_never_deletes_a_hud_verified_clip() -> None:
    clip = ClipWindow(
        start=10.0,
        end=30.0,
        peak=20.0,
        score=0.9,
        reason="AI goal (HUD): LOVELY SCORED",
    )
    reading = make_reading(
        10.0, 15.0, score=0.05, tone="neutral", laughter=False
    )
    adjusted = _apply_audio_reading(
        clip, reading, [], 60.0, "Rocket League", 3.0
    )
    assert adjusted.start == clip.start
    assert adjusted.end == clip.end
    assert adjusted.score == clip.score


def test_hallucinated_reading_does_not_change_a_social_clip() -> None:
    clip = ClipWindow(
        start=10.0,
        end=30.0,
        peak=20.0,
        score=0.75,
        reason='AI banter: "real quote"',
    )
    reading = make_reading(
        10.0, 15.0, score=0.0, trusted=False, speech="fake words"
    )
    adjusted = _apply_audio_reading(
        clip, reading, [], 60.0, "Social", 3.0
    )
    assert adjusted == clip

def test_refine_does_not_erase_scan_confidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    full = tmp_path / "full.jpg"
    hud = tmp_path / "hud.jpg"
    full.write_bytes(b"full")
    hud.write_bytes(b"hud")
    clip = ClipWindow(
        start=10.0,
        end=30.0,
        peak=20.0,
        score=0.9,
        reason='AI banter: "real quote"',
    )
    monkeypatch.setattr(story, "_cache_key", lambda *args, **kwargs: tmp_path / "none.json")
    monkeypatch.setattr(
        story, "_contact_sheet", lambda *args, **kwargs: (full, hud)
    )
    monkeypatch.setattr(
        story,
        "_ollama_chat",
        lambda *args, **kwargs: {
            "keep": True,
            "start": 12.0,
            "end": 28.0,
            "score": 0.0,
            "summary": "a generic summary",
            "evidence": "the quote",
        },
    )
    result = story._refine_clip(
        video,
        clip,
        [],
        40.0,
        "model",
        story.FFmpegBinaries(ffmpeg=Path("ffmpeg"), ffprobe=Path("ffprobe")),
        "Social",
        3.0,
    )
    assert result is not None
    assert result.score >= clip.score
    assert "real quote" in result.reason
    assert result.start == 12.0
    assert result.end == 28.0

def test_social_laughter_without_words_still_counts() -> None:
    clip = ClipWindow(
        start=0.0,
        end=40.0,
        peak=20.0,
        score=0.7,
        reason="AI reaction: signal agreement",
    )
    reading = make_reading(
        28.0,
        33.0,
        score=0.4,
        tone="playful",
        laughter=True,
        speech="",
    )
    adjusted = _apply_audio_reading(
        clip, reading, [], 60.0, "Social", 3.0
    )
    assert adjusted.duration < clip.duration
    assert adjusted.score > clip.score
    assert adjusted.end <= 40.0

def test_same_model_resolves_aliases() -> None:
    assert _same_model("lfm3-omni", "lfm3-omni-2b")
    assert not _same_model("minicpm-o-4.5", "lfm3-omni-2b")
    assert not _same_model("qwen2.5vl:7b", "lfm3-omni-2b")

def test_vram_guard_serialises_default_10gb_pair(monkeypatch) -> None:
    from clipper.detect.llama_runtime import (
        GEMMA_4_12B,
        LFM3_OMNI_2B,
        MINICPM_O_4_5,
    )
    from clipper.gpu import GpuMemory

    monkeypatch.setattr(
        story,
        "query_nvidia_memory",
        lambda: GpuMemory(
            index=0,
            name="RTX 3080",
            uuid="GPU-0",
            total_mb=10240,
            used_mb=0,
            free_mb=10240,
        ),
    )
    assert story._vram_requires_serial(MINICPM_O_4_5, LFM3_OMNI_2B)
    assert story._vram_requires_serial(GEMMA_4_12B, LFM3_OMNI_2B)
    assert not story._vram_requires_serial(LFM3_OMNI_2B, LFM3_OMNI_2B)


def test_vram_guard_allows_both_models_on_16gb(monkeypatch) -> None:
    from clipper.detect.llama_runtime import LFM3_OMNI_2B, MINICPM_O_4_5
    from clipper.gpu import GpuMemory

    monkeypatch.setattr(
        story,
        "query_nvidia_memory",
        lambda: GpuMemory(
            index=0,
            name="RTX 4080",
            uuid="GPU-0",
            total_mb=16384,
            used_mb=1024,
            free_mb=15360,
        ),
    )
    assert not story._vram_requires_serial(MINICPM_O_4_5, LFM3_OMNI_2B)


def test_vram_guard_is_conservative_without_telemetry(monkeypatch) -> None:
    from clipper.detect.llama_runtime import LFM3_OMNI_2B, MINICPM_O_4_5

    monkeypatch.setattr(story, "query_nvidia_memory", lambda: None)
    assert story._vram_requires_serial(MINICPM_O_4_5, LFM3_OMNI_2B)


def test_serial_plan_low_power_forces_serial(monkeypatch) -> None:
    from clipper.detect.llama_runtime import LFM3_OMNI_2B, MINICPM_O_4_5
    from clipper.gpu import GpuMemory

    settings = DetectionSettings(ai=True, ai_ears=True, low_power=True)
    monkeypatch.setattr(
        story,
        "query_nvidia_memory",
        lambda: GpuMemory(
            index=0,
            name="RTX 4090",
            uuid="GPU-0",
            total_mb=24564,
            used_mb=1024,
            free_mb=23540,
        ),
    )
    plan = story._serial_plan(
        settings, False, MINICPM_O_4_5, LFM3_OMNI_2B
    )
    assert plan.serial is True
    assert plan.reason == "low_power"


def test_serial_plan_serialises_when_game_consumes_vram(monkeypatch) -> None:
    from clipper.detect.llama_runtime import LFM3_OMNI_2B, MINICPM_O_4_5
    from clipper.gpu import GpuMemory

    settings = DetectionSettings(ai=True, ai_ears=True, low_power=False)
    monkeypatch.setattr(
        story,
        "query_nvidia_memory",
        lambda: GpuMemory(
            index=0,
            name="RTX 3080",
            uuid="GPU-0",
            total_mb=10240,
            used_mb=3500,
            free_mb=6740,
        ),
    )
    plan = story._serial_plan(
        settings, False, MINICPM_O_4_5, LFM3_OMNI_2B
    )
    assert plan.serial is True
    assert plan.reason == "insufficient"
    assert plan.check is not None
    assert plan.check.free_mb == 6740


def test_serial_plan_allows_concurrent_on_24gb(monkeypatch) -> None:
    from clipper.detect.llama_runtime import LFM3_OMNI_2B, MINICPM_O_4_5
    from clipper.gpu import GpuMemory

    settings = DetectionSettings(ai=True, ai_ears=True, low_power=False)
    monkeypatch.setattr(
        story,
        "query_nvidia_memory",
        lambda: GpuMemory(
            index=0,
            name="RTX 4090",
            uuid="GPU-0",
            total_mb=24564,
            used_mb=4096,
            free_mb=20468,
        ),
    )
    plan = story._serial_plan(
        settings, False, MINICPM_O_4_5, LFM3_OMNI_2B
    )
    assert plan.serial is False
    assert plan.reason == "available"
    assert settings.low_power is False


def test_serial_plan_is_conservative_without_telemetry(monkeypatch) -> None:
    from clipper.detect.llama_runtime import LFM3_OMNI_2B, MINICPM_O_4_5

    settings = DetectionSettings(ai=True, ai_ears=True, low_power=False)
    monkeypatch.setattr(story, "query_nvidia_memory", lambda: None)
    plan = story._serial_plan(
        settings, False, MINICPM_O_4_5, LFM3_OMNI_2B
    )
    assert plan.serial is True
    assert plan.reason == "telemetry_unavailable"


def test_serial_plan_does_not_serialise_same_model(monkeypatch) -> None:
    from clipper.detect.llama_runtime import LFM3_OMNI_2B

    settings = DetectionSettings(ai=True, ai_ears=True, low_power=True)
    monkeypatch.setattr(story, "query_nvidia_memory", lambda: None)
    plan = story._serial_plan(settings, True, LFM3_OMNI_2B, LFM3_OMNI_2B)
    assert plan.serial is False
    assert plan.reason == "not_needed"


def test_configure_with_serial_fallback_retries_vision_only(monkeypatch) -> None:
    from clipper.detect.llama_runtime import LFM3_OMNI_2B, MINICPM_O_4_5
    from clipper.gpu import VramError

    settings = DetectionSettings(ai=True, ai_ears=True, low_power=False)
    calls: list[bool] = []

    def fake_configure(_settings, *, main=True, ears=True):
        calls.append(ears)
        if len(calls) == 1:
            raise VramError("not enough free VRAM")
        return "llamacpp"

    monkeypatch.setattr(story, "configure_runtime", fake_configure)
    messages: list[str] = []
    runtime, serial, warning = story._configure_with_serial_fallback(
        settings, False, lambda _fraction, message: messages.append(message)
    )
    assert runtime == "llamacpp"
    assert serial is True
    assert calls == [True, False]
    assert "sequential inference" in messages[0]
    assert "not enough free VRAM" in warning


def test_configure_with_serial_fallback_reports_failure(monkeypatch) -> None:
    from clipper.gpu import VramError

    settings = DetectionSettings(ai=True, ai_ears=True, low_power=False)

    def fake_configure(_settings, *, main=True, ears=True):
        raise VramError("still not enough free VRAM")

    monkeypatch.setattr(story, "configure_runtime", fake_configure)
    with pytest.raises(story.AIError, match="still not enough"):
        story._configure_with_serial_fallback(settings, True, None)


def test_serial_plan_low_power_without_bundled_main(monkeypatch) -> None:
    from clipper.detect.llama_runtime import LFM3_OMNI_2B

    settings = DetectionSettings(ai=True, ai_ears=True, low_power=True)
    monkeypatch.setattr(story, "query_nvidia_memory", lambda: None)
    plan = story._serial_plan(settings, False, None, LFM3_OMNI_2B)
    assert plan.serial is True
    assert plan.reason == "low_power"


def test_refine_placeholders_are_discarded() -> None:
    assert _clean_model_text("one short sentence") == ""
    assert _clean_model_text("The concrete proof or the contradiction.") == ""
    assert _clean_model_text("Real proof from the HUD") == "Real proof from the HUD"
