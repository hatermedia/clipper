from __future__ import annotations

import importlib.util

import pytest

from clipper.config import DetectionSettings, default_threads
from clipper.ffmpeg import resolve_encoder


def test_defaults_are_balanced() -> None:
    settings = DetectionSettings()
    assert 2 <= settings.threads <= 8
    assert settings.threads == default_threads()
    assert settings.proxy_width == 320
    assert settings.gpu is False


def test_low_power_caps() -> None:
    settings = DetectionSettings(threads=16, sample_fps=8, proxy_width=480)
    settings.apply_low_power()
    assert settings.threads == 2
    assert settings.sample_fps == 2
    assert settings.proxy_width == 256
    assert settings.low_power is True


def test_auto_encoder_resolves() -> None:
    from clipper.config import FFmpegNotFound, find_ffmpeg

    try:
        find_ffmpeg()
    except FFmpegNotFound:
        pytest.skip("ffmpeg is not available")
    assert resolve_encoder("auto") in {"h264_nvenc", "libx264"}


def test_invalid_threads_rejected() -> None:
    with pytest.raises(ValueError):
        DetectionSettings(threads=-1).validate()


desktop_available = importlib.util.find_spec("PySide6") is not None


@pytest.mark.skipif(not desktop_available, reason="PySide6 not installed")
def test_desktop_smoke(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from clipper.desktop import main

    assert main(["--smoke-test"]) == 0
