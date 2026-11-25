from __future__ import annotations

import inspect

import pytest

PySide6 = pytest.importorskip("PySide6")

from clipper.desktop import MainWindow  # noqa: E402


def test_screen_clamp_uses_logical_available_geometry() -> None:
    source = inspect.getsource(MainWindow._clamp_to_screen)
    assert "availableGeometry()" in source
    assert "devicePixelRatioF" not in source
    assert "/ self.devicePixelRatio" not in source


def test_titlebar_hit_testing_uses_laid_out_header_and_widgets() -> None:
    source = inspect.getsource(MainWindow.nativeEvent)
    assert "_header_layout" in source
    assert "childAt" in source
    assert "QAbstractButton" in source


def test_close_event_stops_previews_workers_and_ffmpeg() -> None:
    source = inspect.getsource(MainWindow.closeEvent)
    assert "ClipPreviewDialog" in source
    assert "terminate_active_processes" in source
    assert "cleanup_download" in source
    assert "self._update_shutdown" in source
