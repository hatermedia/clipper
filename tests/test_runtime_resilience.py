from __future__ import annotations

import sys
import time
import types

import numpy as np
import pytest

from clipper.detect import hud, signals


def test_hud_samples_start_and_end_of_each_block() -> None:
    assert hud.HUD_SAMPLE_OFFSETS[0] == 0.0
    assert hud.HUD_SAMPLE_OFFSETS[-1] == 1.0
    assert list(hud.HUD_SAMPLE_OFFSETS) == sorted(set(hud.HUD_SAMPLE_OFFSETS))
    assert len(hud.HUD_SAMPLE_OFFSETS) >= 5


def test_hud_engine_retries_after_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"count": 0}

    class FailingRapidOCR:
        def __init__(self) -> None:
            attempts["count"] += 1
            raise RuntimeError("OCR init failed")

    fake = types.ModuleType("rapidocr_onnxruntime")
    fake.RapidOCR = FailingRapidOCR  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", fake)
    monkeypatch.setattr(hud, "_ENGINE", None)
    monkeypatch.setattr(hud, "_ENGINE_FAILED_AT", 0.0)

    assert hud._engine() is None
    assert hud._engine() is None
    assert attempts["count"] == 1

    monkeypatch.setattr(hud, "_ENGINE_FAILED_AT", time.monotonic() - 61.0)
    assert hud._engine() is None
    assert attempts["count"] == 2


def test_hud_runtime_failure_resets_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pathlib import Path

    class FailingEngine:
        def __call__(self, *_args, **_kwargs):
            raise RuntimeError("OCR crashed")

    monkeypatch.setattr(hud, "_ENGINE", FailingEngine())
    monkeypatch.setattr(hud, "_ENGINE_FAILED_AT", 0.0)
    monkeypatch.setattr(hud, "make_thumbnail", lambda *args, **kwargs: None)

    reading = hud.read_hud(
        Path("clip.mp4"),
        0.0,
        10.0,
        object(),  # type: ignore[arg-type]
        samples=(0.0, 1.0),
    )
    assert not reading.available
    assert hud._ENGINE is None
    assert hud._ENGINE_FAILED_AT > 0.0


@pytest.mark.skipif(
    not signals.YAMNET_MODEL.is_file() or not signals.YAMNET_CLASSES.is_file(),
    reason="YAMNet assets are not present",
)
def test_yamnet_retries_after_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    import onnxruntime as ort

    attempts = {"count": 0}

    def fail(*args, **kwargs):
        attempts["count"] += 1
        raise RuntimeError("session init failed")

    monkeypatch.setattr(ort, "InferenceSession", fail)
    monkeypatch.setattr(signals, "_YAMNET_SESSION", None)
    monkeypatch.setattr(signals, "_YAMNET_FAILED_AT", 0.0)

    assert signals._yamnet_session(1) is None
    assert signals._yamnet_session(1) is None
    assert attempts["count"] == 1

    monkeypatch.setattr(signals, "_YAMNET_FAILED_AT", time.monotonic() - 61.0)
    assert signals._yamnet_session(1) is None
    assert attempts["count"] == 2


def test_yamnet_inference_failure_resets_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeInput:
        name = "input"

    class BrokenSession:
        def get_inputs(self):
            return [FakeInput()]

        def run(self, *_args, **_kwargs):
            raise RuntimeError("inference crashed")

    monkeypatch.setattr(signals, "_YAMNET_SESSION", BrokenSession())
    monkeypatch.setattr(signals, "_YAMNET_FAILED_AT", 0.0)
    monkeypatch.setattr(
        signals,
        "_yamnet_indices",
        lambda: {"laugh": [1], "cheer": [2], "shout": [3]},
    )

    result = signals._yamnet_track(np.zeros(16000, dtype=np.float32), 16000)
    assert all(array.size == 0 for array in result)
    assert signals._YAMNET_SESSION is None
    assert signals._YAMNET_FAILED_AT > 0.0
