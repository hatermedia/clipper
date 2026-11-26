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


def test_ai_setup_installs_ollama_from_inside_the_app() -> None:
    source = Path(inspect.getsourcefile(MainWindow)).read_text(encoding="utf-8")
    assert "OllamaInstallWorker" in source
    assert "Install Ollama" in source
    assert "install_prerequisite" in source
    assert "ai_setup_progress" in source
    assert "https://ollama.com/download" not in source


def test_browse_and_drop_zone_open_native_pickers_directly() -> None:
    source = inspect.getsource(MainWindow.choose_input)
    assert "choose_folder" in source
    assert "QMenu" not in source
    full = Path(inspect.getsourcefile(MainWindow)).read_text(encoding="utf-8")
    assert "self.drop.clicked.connect(self.choose_video)" in full
    assert "QFileDialog.getExistingDirectory" in full
    assert "QFileDialog.getOpenFileName" in full


def test_legacy_ai_mode_and_game_picker_are_removed() -> None:
    source = Path(inspect.getsourcefile(MainWindow)).read_text(encoding="utf-8")
    assert "Fast review" not in source
    assert "Lite review" not in source
    assert "legacy peak-only" not in source
    assert "self.ai_game" not in source
    assert "self.ai_mode." not in source
    assert "self.ai." not in source
    assert "ai_game=\"auto\"" in source
    assert "ai_mode=\"director\"" in source
    assert "Local AI director" in source
    assert "is_supported_vision_model" in source
    assert "QInputDialog.getItem" in source
    assert "launch_ollama_server" in source
    assert "self.left_scroll" in source
    assert "Other local models" not in source
    assert "Custom model" not in source


def test_frame_accurate_reencode_and_discord_copy_are_removed() -> None:
    source = Path(inspect.getsourcefile(MainWindow)).read_text(encoding="utf-8")
    assert "Frame-accurate re-encode" not in source
    assert "self.reencode" not in source
    assert "Discord" not in source
    assert "Lossless cuts" in source
    assert "heuristic-only" not in source
    assert "turn off" not in source.lower()


def test_update_flow_persists_and_resumes_pending_installer() -> None:
    source = Path(inspect.getsourcefile(MainWindow)).read_text(encoding="utf-8")
    assert "_resume_pending_update" in source
    assert "save_pending_update" in source
    assert "load_pending_update" in source
    assert "cached_installer_path" in source
    assert "launch_installer" in source
    update_source = (Path(inspect.getsourcefile(MainWindow)).parent / "update.py").read_text(
        encoding="utf-8"
    )
    assert "_wait_for_helper_marker" in update_source
    assert "helper did not confirm startup" in update_source


def test_close_event_stops_previews_workers_and_ffmpeg() -> None:
    source = inspect.getsource(MainWindow.closeEvent)
    assert "ClipPreviewDialog" in source
    assert "terminate_active_processes" in source
    assert "cleanup_download" in source
    assert "self._update_shutdown" in source

def test_gui_exposes_grouped_models_and_intentional_empty_states() -> None:
    source = Path(inspect.getsourcefile(MainWindow)).read_text(encoding="utf-8")
    assert "_add_combo_header" in source
    assert '"Bundled"' in source
    assert '"Ollama"' in source
    assert '"Other Ollama models"' not in source
    assert "_custom_ollama_models" not in source
    assert "No highlights yet" in source
    assert "No clip selected" in source
    assert "partially ready" in source
    assert "Quick start" in source
    assert "Significantly slower: every video reloads them" in source
