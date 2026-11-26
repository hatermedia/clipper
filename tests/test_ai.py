from pathlib import Path

import pytest

from clipper.config import DetectionSettings, ai_confidence_for_sensitivity
from clipper.detect import ai
from clipper.detect.ai import is_supported_vision_model, num_gpu_for
from clipper.models import ClipWindow


def test_small_vision_model_uses_partial_gpu_offload() -> None:
    assert num_gpu_for("qwen2.5vl:3b") == 20
    assert num_gpu_for("qwen2.5vl:7b") == 99


def test_legacy_modes_are_rejected() -> None:
    for mode in ("review", "lite"):
        with pytest.raises(ValueError, match="director"):
            DetectionSettings(ai_mode=mode).validate()


def test_only_supported_vision_families_are_offered() -> None:
    assert is_supported_vision_model("gemma3:4b")
    assert is_supported_vision_model("qwen2.5vl:7b")
    assert is_supported_vision_model("qwen3-vl:4b")
    assert not is_supported_vision_model("qwen2.5vl:3b")
    assert not is_supported_vision_model("qwen3:14b")
    assert not is_supported_vision_model("Godmoded/llama3-lexi-uncensored:latest")


def test_sensitivity_presets_map_to_ai_thresholds() -> None:
    strict = ai_confidence_for_sensitivity(0.32)
    balanced = ai_confidence_for_sensitivity(0.50)
    loose = ai_confidence_for_sensitivity(0.78)
    assert strict > balanced > loose
    assert 0.45 <= loose <= 0.55 <= balanced <= strict <= 0.70


def test_malformed_ollama_json_does_not_abort_other_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ai, "model_available", lambda _model: True)
    calls: list[float] = []

    def fake_review(*args, **kwargs):
        calls.append(1.0)
        if len(calls) == 1:
            raise ai.AIError("Ollama returned malformed JSON: truncated")
        return {
            "highlight": True,
            "confidence": 0.95,
            "best_frame": 2,
            "category": "funny",
            "reason": "clear reaction",
        }

    monkeypatch.setattr(ai, "review_window", fake_review)
    candidates = [
        ClipWindow(start=1.0, end=13.0, peak=7.0, score=0.8),
        ClipWindow(start=20.0, end=32.0, peak=26.0, score=0.8),
    ]
    clips, warnings = ai.review_candidates(
        Path("clip.mp4"),
        candidates,
        DetectionSettings(ai_model="test-model"),
        40.0,
    )
    assert len(calls) == 2
    assert len(clips) == 1
    assert any("malformed JSON" in warning for warning in warnings)

