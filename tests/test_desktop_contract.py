from __future__ import annotations

import inspect
from pathlib import Path

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


def test_update_button_has_no_mnemonic_ampersand() -> None:
    source = Path(inspect.getsourcefile(MainWindow)).read_text(encoding="utf-8")
    assert 'setText("Restart and install")' in source
    assert "Restart & install" not in source


def test_tooltips_have_delay_and_click_guards() -> None:
    source = Path(inspect.getsourcefile(MainWindow)).read_text(encoding="utf-8")
    assert "self._show_timer.setInterval(1000)" in source
    assert "self._hide_timer.setInterval(500)" in source
    assert "QWidget#TitleBar" in source
    assert "QToolTip.showText" in source


def test_highlights_are_flat_and_use_inline_player() -> None:
    source = Path(inspect.getsourcefile(MainWindow)).read_text(encoding="utf-8")
    assert "InlineClipPreview" in source
    assert "setRootIsDecorated(False)" in source
    assert "itemClicked.connect" not in source
    assert "_open_clip_preview" not in source
    assert "self.preview_player.load" in source


def test_close_event_stops_previews_workers_and_ffmpeg() -> None:
    source = inspect.getsource(MainWindow.closeEvent)
    assert "ClipPreviewDialog" in source
    assert "terminate_active_processes" in source
    assert "cleanup_download" in source
    assert "self._update_shutdown" in source
