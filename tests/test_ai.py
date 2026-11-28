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


def test_explicit_local_server_model_uses_server_runtime() -> None:
    settings = DetectionSettings(
        ai=True,
        ai_model="server:local-vision",
        ai_server_url="http://127.0.0.1:1234",
        ai_ears=False,
    )
    try:
        assert ai.configure_runtime(settings) == "server"
        assert ai.runtime_name() == "server"
    finally:
        ai.stop_runtime()

def test_configure_runtime_propagates_vram_error(monkeypatch) -> None:
    from clipper.detect import llama_runtime
    from clipper.gpu import VramError

    settings = DetectionSettings(
        ai=True,
        ai_model="minicpm-o-4.5",
        ai_ears=True,
        ai_ears_model="lfm3-omni-2b",
        ai_runtime="auto",
    )
    monkeypatch.setattr(llama_runtime, "runtime_ready", lambda: True)
    monkeypatch.setattr(llama_runtime, "model_ready", lambda _spec: True)
    monkeypatch.setattr(
        llama_runtime,
        "start_server",
        lambda _spec: (_ for _ in ()).throw(VramError("no headroom")),
    )
    try:
        with pytest.raises(VramError, match="no headroom"):
            ai.configure_runtime(settings)
        assert ai.runtime_name() == "ollama"
    finally:
        ai.stop_runtime()


def test_configure_runtime_propagates_vram_error_after_vision_load(
    monkeypatch,
) -> None:
    from clipper.detect import llama_runtime
    from clipper.gpu import VramError

    settings = DetectionSettings(
        ai=True,
        ai_model="minicpm-o-4.5",
        ai_ears=True,
        ai_ears_model="lfm3-omni-2b",
        ai_runtime="auto",
    )
    started = []

    class FakeServer:
        def stop(self) -> None:
            started.clear()

    def fake_start(spec):
        if started:
            raise VramError("ears need more memory")
        started.append(spec.id)
        return FakeServer()

    monkeypatch.setattr(llama_runtime, "runtime_ready", lambda: True)
    monkeypatch.setattr(llama_runtime, "model_ready", lambda _spec: True)
    monkeypatch.setattr(llama_runtime, "start_server", fake_start)
    try:
        with pytest.raises(VramError, match="ears need more memory"):
            ai.configure_runtime(settings)
        assert started == ["minicpm-o-4.5"]
    finally:
        ai.stop_runtime()


def test_external_server_url_is_validated() -> None:
    settings = DetectionSettings(
        ai=True,
        ai_model="server:local-vision",
        ai_server_url="file:///C:/Windows/win.ini",
        ai_ears=False,
    )
    try:
        with pytest.raises(ai.AIError, match="http"):
            ai.configure_runtime(settings)
        assert ai.runtime_name() != "server"
    finally:
        ai.stop_runtime()
