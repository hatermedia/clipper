"""Native Qt desktop app for Clipper.

This is the primary Windows experience: native folder picker, drag-and-drop,
GPU/NVENC toggle, CPU caps, low-power mode, previews, and export without a
browser or a permanently open command prompt.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import threading
import traceback
from dataclasses import replace
from pathlib import Path

# Windows Media Foundation is the native backend and avoids FFmpeg plugin
# crashes on some NVIDIA-trimmed captures. Must be set before QtMultimedia loads.
if os.name == "nt":
    os.environ.setdefault("QT_MEDIA_BACKEND", "windows")

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QSettings,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Property,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFontDatabase,
    QGuiApplication,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QToolTip,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .ai_setup import (
    AISetupCancelled,
    AISetupError,
    install_prerequisite,
    ollama_executable,
    start_ollama_server,
)
from .config import (
    Cancelled,
    ClipperError,
    DetectionSettings,
    ai_confidence_for_sensitivity,
    default_threads,
    find_ffmpeg,
    set_low_priority,
)
from .detect.ai import DEFAULT_MODEL, ollama_status, unload_model
from .ffmpeg import (
    FFmpegError,
    ffmpeg_version,
    nvenc_available,
    nvidia_memory_mb,
    terminate_active_processes,
)
from .gameguard import detect_running_game
from .models import AnalysisSummary
from .pipeline import analyze_target, export_analysis, scan_inputs
from .update import (
    ReleaseInfo,
    UpdateError,
    check_with_cache,
    cleanup_download,
    download_installer,
    is_installed_build,
    launch_installer,
    open_release_page,
)

ASSET_DIR = Path(__file__).resolve().parent / "assets"
VIDEO_ICON = ASSET_DIR / "icon.png"
TOGGLE_ON_ICON = (ASSET_DIR / "toggle_on.png").as_posix()
TOGGLE_OFF_ICON = (ASSET_DIR / "toggle_off.png").as_posix()
CHEVRON_DOWN_ICON = (ASSET_DIR / "chevron_down.png").as_posix()
CHEVRON_UP_ICON = (ASSET_DIR / "chevron_up.png").as_posix()
ROLE_PREVIEW = int(Qt.UserRole)
ROLE_VIDEO = ROLE_PREVIEW + 1
ROLE_START = ROLE_PREVIEW + 2
ROLE_END = ROLE_PREVIEW + 3
ROLE_INDEX = ROLE_PREVIEW + 4
ROLE_NAME = ROLE_PREVIEW + 5


STYLESHEET = """
QWidget {
    background: #1a1a1a;
    color: #f2f2f2;
    font-family: "Inter";
    font-size: 13px;
}
QMainWindow { background: #1a1a1a; }
QLabel { background: transparent; }
QFrame#Panel {
    background: #222222;
    border: 1px solid #333333;
    border-radius: 8px;
}
QFrame#DropZone {
    background: #202020;
    border: 1px dashed #484848;
    border-radius: 7px;
}
QFrame#DropZone:hover { border-color: #2f9bff; }
QLabel#Brand {
    font-size: 18px;
    font-weight: 700;
    color: #ffffff;
}
QLabel#BrandSub {
    color: #8f8f8f;
    font-size: 10px;
}
QLabel#Section {
    font-size: 15px;
    font-weight: 600;
    color: #f7f7f7;
}
QLabel#Muted { color: #9e9e9e; font-size: 11px; }
QLabel#Status { color: #9e9e9e; font-size: 11px; }
QLabel#Summary { color: #9e9e9e; font-size: 11px; }
QFrame#PreviewPanel {
    background: #202020;
    border: 1px solid #333333;
    border-radius: 7px;
}
QLabel#Preview {
    background: #202020;
    border: 1px solid #333333;
    border-radius: 7px;
    color: #777777;
}
QPushButton {
    background: #2b2b2b;
    border: 1px solid #3b3b3b;
    border-radius: 7px;
    padding: 7px 12px;
    color: #eeeeee;
    font-weight: 500;
}
QPushButton:hover { background: #333333; border-color: #555555; }
QPushButton:pressed { background: #262626; }
QPushButton:disabled { color: #666666; background: #232323; border-color: #303030; }
QPushButton#Primary {
    background: #2f9bff;
    color: #0b0b0b;
    font-weight: 600;
    border: none;
    padding: 8px 14px;
}
QPushButton#Primary:hover { background: #55adff; }
QPushButton#Primary:pressed { background: #1f83dd; }
QPushButton#Primary:disabled { background: #2a3a48; color: #77838c; }
QPushButton#Accent {
    background: #2f9bff;
    color: #0b0b0b;
    border: none;
    font-weight: 600;
    padding: 6px 12px;
}
QPushButton#Accent:hover { background: #55adff; }
QPushButton#Accent:pressed { background: #1f83dd; }
QPushButton#Accent:disabled { background: #2a3a48; color: #77838c; }
QPushButton#Preset {
    background: #2b2b2b;
    border: 1px solid #3b3b3b;
    color: #d8d8d8;
}
QPushButton#Preset:checked {
    background: #2f9bff;
    border-color: #2f9bff;
    color: #0b0b0b;
    font-weight: 600;
}
QPushButton#Mono { font-size: 11px; padding: 5px 9px; }
QWidget#TitleBar {
    background: #1a1a1a;
    border-bottom: 1px solid #2a2a2a;
}
QPushButton#WindowButton {
    background: transparent;
    border: none;
    border-radius: 0;
    color: #b0b0b0;
    padding: 0;
}
QPushButton#WindowButton:hover { background: #333333; color: #ffffff; }
QPushButton#WindowClose {
    background: transparent;
    border: none;
    border-radius: 0;
    color: #b0b0b0;
    padding: 0;
}
QPushButton#WindowClose:hover { background: #d9534f; color: #ffffff; }
QPushButton#IconButton {
    background: transparent;
    border: none;
    color: #a8a8a8;
    font-size: 17px;
    padding: 0;
}
QPushButton#IconButton:hover { background: #333333; color: #ffffff; }
QLabel#ToggleLabel { font-size: 13px; color: #f2f2f2; }
QLabel#ToggleState { font-size: 11px; color: #d0d0d0; min-width: 18px; }
QLabel#Help {
    color: #a8a8a8;
    border: 1px solid #4a4a4a;
    border-radius: 7px;
    min-width: 14px;
    max-width: 14px;
    min-height: 14px;
    max-height: 14px;
    font-size: 9px;
    background: #2b2b2b;
}
QLabel#Help:hover { color: #ffffff; border-color: #2f9bff; background: #333333; }
QFrame#UpdateBar {
    background: #242424;
    border: 1px solid #383838;
    border-left: 3px solid #2f9bff;
    border-radius: 7px;
}
QFrame#AiSetup {
    background: #232323;
    border: 1px solid #383838;
    border-left: 3px solid #2f9bff;
    border-radius: 7px;
}
QLabel#AiSetupTitle { color: #ffffff; font-weight: 600; font-size: 12px; }
QFrame#UpdateBar QLabel { color: #d8d8d8; font-size: 12px; }
QFrame#UpdateBar QPushButton { padding: 5px 10px; }
QLineEdit, QComboBox, QSpinBox {
    background: #2b2b2b;
    border: 1px solid #3b3b3b;
    border-radius: 6px;
    padding: 6px 8px;
    color: #f2f2f2;
    selection-background-color: #2f9bff;
    selection-color: #0b0b0b;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #2f9bff; }
QComboBox QAbstractItemView {
    background: #2b2b2b;
    border: 1px solid #4a4a4a;
    selection-background-color: #2f9bff;
    selection-color: #0b0b0b;
    outline: 0;
}
QGroupBox {
    background: #222222;
    border: 1px solid #333333;
    border-radius: 8px;
    margin-top: 14px;
    padding: 16px 12px 10px 12px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 4px;
    font-size: 15px;
    font-weight: 600;
    color: #f7f7f7;
}
QSlider::groove:horizontal { height: 4px; background: #3a3a3a; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 14px; margin: -6px 0; border-radius: 7px;
    background: #f2f2f2;
}
QSlider::handle:horizontal:hover { background: #ffffff; }
QSlider::sub-page:horizontal { background: #2f9bff; border-radius: 2px; }
QProgressBar {
    background: #2b2b2b;
    border: none;
    border-radius: 3px;
    text-align: center;
    color: #b8b8b8;
    height: 12px;
    font-size: 9px;
}
QProgressBar::chunk { background: #2f9bff; border-radius: 3px; }
QTreeWidget {
    background: #202020;
    border: 1px solid #333333;
    border-radius: 7px;
    alternate-background-color: #232323;
    outline: 0;
}
QTreeWidget::item { padding: 5px 4px; border: none; }
QTreeWidget::item:selected { background: #2f2f2f; color: #ffffff; }
QHeaderView::section {
    background: #242424;
    color: #9e9e9e;
    border: 0;
    border-bottom: 1px solid #333333;
    padding: 7px 8px;
    font-size: 10px;
    font-weight: 600;
}
QListWidget {
    background: #202020;
    border: 1px solid #333333;
    border-radius: 6px;
    color: #b8b8b8;
    outline: 0;
}
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: #3c3c3c; border-radius: 4px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #4a4a4a; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }
QScrollBar::handle:horizontal { background: #3c3c3c; border-radius: 4px; min-width: 24px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QSplitter::handle { background: #1a1a1a; }
QSplitter::handle:hover { background: #2f2f2f; }
QToolTip {
    background: #2b2b2b;
    color: #f2f2f2;
    border: 1px solid #4a4a4a;
    padding: 6px;
    font-size: 11px;
}
QDialog { background: transparent; }
QFrame#DialogPanel {
    background: #2a2a2a;
    border: 1px solid #404040;
    border-radius: 10px;
}
QLabel#DialogTitle { font-size: 13px; font-weight: 600; color: #f2f2f2; }
QLabel#DialogMessage { font-size: 14px; color: #f2f2f2; }
QVideoWidget { background: #000000; }
QLabel#PreviewTime { font-size: 11px; color: #a8a8a8; }
"""


class AnalyzeWorker(QThread):
    progress = Signal(float, str)
    file_done = Signal(object)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, path: str, settings: DetectionSettings, recursive: bool, preview_dir: Path) -> None:
        super().__init__()
        self.path = path
        self.settings = settings
        self.recursive = recursive
        self.preview_dir = preview_dir
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def _progress(self, fraction: float, message: str) -> None:
        if self._cancel:
            raise Cancelled("cancelled")
        self.progress.emit(fraction, message)

    def run(self) -> None:
        try:
            summary = analyze_target(
                self.path,
                self.settings,
                recursive=self.recursive,
                preview_dir=self.preview_dir,
                progress=self._progress,
                on_file_done=self.file_done.emit,
            )
            self.done.emit(summary)
        except Cancelled:
            self.failed.emit("Cancelled")
        except Exception as exc:
            self.failed.emit(str(exc))


class ExportWorker(QThread):
    progress = Signal(float, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        summary: AnalysisSummary,
        output_dir: str,
        reencode: bool,
        encoder: str,
        crf: int,
        threads: int,
    ) -> None:
        super().__init__()
        self.summary = summary
        self.output_dir = output_dir
        self.reencode = reencode
        self.encoder = encoder
        self.crf = crf
        self.threads = threads
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def _progress(self, fraction: float, message: str) -> None:
        if self._cancel:
            raise Cancelled("cancelled")
        self.progress.emit(fraction, message)

    def run(self) -> None:
        try:
            result = export_analysis(
                self.summary,
                output_dir=self.output_dir,
                reencode=self.reencode,
                encoder=self.encoder,
                crf=self.crf,
                preset="veryfast",
                progress=self._progress,
                threads=self.threads,
            )
            self.done.emit(result)
        except Cancelled:
            self.failed.emit("Cancelled")
        except Exception as exc:
            self.failed.emit(str(exc))


class UpdateCheckWorker(QThread):
    found = Signal(object)
    failed = Signal(str)

    def __init__(self, force: bool = False) -> None:
        super().__init__()
        self.force = force

    def run(self) -> None:
        try:
            release, _cached = check_with_cache(force=self.force)
            self.found.emit(release)
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))


class UpdateDownloadWorker(QThread):
    progress = Signal(int, int)
    ready = Signal(str)
    failed = Signal(str)

    def __init__(self, release: ReleaseInfo) -> None:
        super().__init__()
        self.release = release

    def run(self) -> None:
        try:
            path = download_installer(
                self.release,
                progress=self._progress,
            )
            self.ready.emit(str(path))
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))

    def _progress(self, done: int, total: int) -> None:
        if self.isInterruptionRequested():
            raise UpdateError("Download cancelled.")
        self.progress.emit(done, total)


class OllamaPullWorker(QThread):
    line = Signal(str)
    done = Signal(bool, str)

    def __init__(self, model: str) -> None:
        super().__init__()
        self.model = model
        self._process: subprocess.Popen[str] | None = None

    def cancel(self) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def run(self) -> None:
        exe = ollama_executable()
        if exe is None:
            self.done.emit(False, "Ollama is not installed or not on PATH.")
            return
        try:
            process = subprocess.Popen(
                [str(exe), "pull", self.model],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
        except OSError as exc:
            self.done.emit(False, str(exc))
            return
        self._process = process
        if process.stdout is not None:
            for raw in process.stdout:
                line = raw.strip()
                if line:
                    self.line.emit(line)
        code = process.wait()
        self._process = None
        if code == 0:
            self.done.emit(True, f"{self.model} is ready.")
        else:
            self.done.emit(False, f"ollama pull exited with code {code}.")


class OllamaInstallWorker(QThread):
    progress = Signal(int, int)
    status = Signal(str)
    done = Signal(bool, str)

    def __init__(self) -> None:
        super().__init__()
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()
        self.requestInterruption()

    def run(self) -> None:
        try:
            executable = install_prerequisite(
                progress=self._progress,
                status=self.status.emit,
                cancelled=self._cancel.is_set,
            )
            self.done.emit(True, f"Ollama is installed at {executable.parent}.")
        except AISetupCancelled as exc:
            self.done.emit(False, str(exc))
        except AISetupError as exc:
            self.done.emit(False, str(exc))
        except Exception as exc:  # Keep a failed install from closing the app.
            self.done.emit(False, f"Ollama setup failed: {exc}")

    def _progress(self, done: int, total: int) -> None:
        if self._cancel.is_set():
            raise AISetupCancelled("Ollama download cancelled. Retry to resume it.")
        self.progress.emit(done, total)


class ClickablePreview(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


def _window_icon(kind: str) -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor("#d6d6d6"))
    pen.setWidthF(2.0)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    if kind == "min":
        painter.drawLine(10, 17, 22, 17)
    elif kind == "max":
        painter.drawRect(10, 10, 12, 12)
    elif kind == "restore":
        painter.drawRect(9, 13, 10, 10)
        painter.drawLine(13, 9, 23, 9)
        painter.drawLine(23, 9, 23, 19)
        painter.drawLine(19, 19, 23, 19)
    elif kind == "close":
        painter.drawLine(10, 10, 22, 22)
        painter.drawLine(22, 10, 10, 22)
    painter.end()
    return QIcon(pixmap)


class InlineClipPreview(QFrame):
    """Inline video player for the selected highlight."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PreviewPanel")
        self.setFixedHeight(320)
        self._video_path = ""
        self._start_ms = 0
        self._end_ms = 0
        self._loaded = False
        self._seeked = False
        self._pending_seek = False
        self._want_play = False
        self._at_end = False
        self._dragging = False
        self._poster_source = QPixmap()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.poster = ClickablePreview("Select a clip to preview")
        self.poster.setObjectName("Preview")
        self.poster.setAlignment(Qt.AlignCenter)
        self.poster.setCursor(Qt.PointingHandCursor)
        self.poster.setToolTip("Click Play to watch this clip")
        self.poster.clicked.connect(self.toggle_play)
        self.video = QVideoWidget()
        self.video.setMinimumHeight(220)
        self.stack.addWidget(self.poster)
        self.stack.addWidget(self.video)
        layout.addWidget(self.stack, 1)

        controls = QHBoxLayout()
        controls.setContentsMargins(8, 5, 8, 7)
        controls.setSpacing(6)
        self.play_btn = QPushButton("Play")
        self.play_btn.setFixedWidth(70)
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self.toggle_play)
        controls.addWidget(self.play_btn)
        back_btn = QPushButton("-5s")
        back_btn.setFixedWidth(52)
        back_btn.clicked.connect(lambda: self.seek_relative(-5000))
        controls.addWidget(back_btn)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1)
        self.slider.setEnabled(False)
        self.slider.sliderPressed.connect(self._slider_pressed)
        self.slider.sliderReleased.connect(self._slider_released)
        self.slider.sliderMoved.connect(self._slider_moved)
        controls.addWidget(self.slider, 1)
        ahead_btn = QPushButton("+5s")
        ahead_btn.setFixedWidth(52)
        ahead_btn.clicked.connect(lambda: self.seek_relative(5000))
        controls.addWidget(ahead_btn)
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setObjectName("PreviewTime")
        self.time_label.setMinimumWidth(88)
        controls.addWidget(self.time_label)
        self.open_btn = QPushButton("Open")
        self.open_btn.setToolTip("Open the source video in the default player")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self._video_path))
        )
        controls.addWidget(self.open_btn)
        layout.addLayout(controls)

        self.error_label = QLabel("")
        self.error_label.setObjectName("Muted")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.85)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self._position_changed)
        self.player.playbackStateChanged.connect(self._state_changed)
        self.player.mediaStatusChanged.connect(self._media_status)
        self.player.errorOccurred.connect(self._player_error)

    def load(
        self,
        video_path: str,
        start: float,
        end: float,
        poster_path: str | None = None,
    ) -> None:
        self.player.stop()
        self._video_path = video_path
        self._start_ms = max(0, int(start * 1000))
        self._end_ms = max(self._start_ms + 250, int(end * 1000))
        self._loaded = True
        self._seeked = False
        self._pending_seek = True
        self._want_play = False
        self._at_end = False
        self._dragging = False
        self.error_label.hide()
        self.error_label.setText("")

        self._poster_source = QPixmap(poster_path) if poster_path else QPixmap()
        self.stack.setCurrentWidget(self.poster)
        if self._poster_source.isNull():
            self.poster.clear()
            self.poster.setText("Press Play to preview this clip")
        else:
            self.poster.setText("")
            self._scale_poster()

        duration = self._end_ms - self._start_ms
        self.slider.setRange(0, max(1, duration))
        self.slider.setValue(0)
        self.slider.setEnabled(True)
        self.play_btn.setEnabled(True)
        self.open_btn.setEnabled(True)
        self.time_label.setText(f"0:00 / {self._mmss(duration)}")
        self.player.setSource(QUrl.fromLocalFile(str(Path(video_path))))

    def clear(self) -> None:
        self._loaded = False
        self._seeked = False
        self._pending_seek = False
        self._want_play = False
        self._at_end = False
        self._dragging = False
        self._video_path = ""
        self._poster_source = QPixmap()
        self.player.stop()
        self.player.setSource(QUrl())
        self.stack.setCurrentWidget(self.poster)
        self.poster.clear()
        self.poster.setText("Select a clip to preview")
        self.error_label.hide()
        self.error_label.setText("")
        self.slider.setRange(0, 1)
        self.slider.setValue(0)
        self.slider.setEnabled(False)
        self.play_btn.setText("Play")
        self.play_btn.setEnabled(False)
        self.open_btn.setEnabled(False)
        self.time_label.setText("0:00 / 0:00")

    def release_media(self) -> None:
        self.clear()

    def toggle_play(self) -> None:
        if not self._loaded:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._want_play = False
            self.player.pause()
            return
        if (
            self._at_end
            or not self._seeked
            or self.player.position() < self._start_ms
            or self.player.position() >= self._end_ms
        ):
            self._at_end = False
            self.player.setPosition(self._start_ms)
        self._want_play = True
        self.stack.setCurrentWidget(self.video)
        self.player.play()

    def seek_relative(self, delta_ms: int) -> None:
        if not self._loaded:
            return
        position = self.player.position() + delta_ms
        position = max(self._start_ms, min(self._end_ms - 100, position))
        self._at_end = False
        self.player.setPosition(position)

    def _slider_pressed(self) -> None:
        self._dragging = True

    def _slider_released(self) -> None:
        self._dragging = False
        self._at_end = False
        self.player.setPosition(self._start_ms + self.slider.value())

    def _slider_moved(self, value: int) -> None:
        self._at_end = False
        self.player.setPosition(self._start_ms + value)

    def _media_status(self, status) -> None:
        if status in {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        } and self._pending_seek:
            self._pending_seek = False
            self.player.setPosition(self._start_ms)
            self._seeked = True
            if self._want_play:
                self.player.play()
            else:
                self.player.pause()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._player_error(None, "This video codec cannot be previewed here.")

    def _player_error(self, error, message: str) -> None:
        self.error_label.setText(
            f"Preview unavailable: {message or 'codec not supported'}. "
            "Use Open to play the source file."
        )
        self.error_label.show()
        self.stack.setCurrentWidget(self.poster)

    def _position_changed(self, position: int) -> None:
        if not self._seeked:
            return
        duration = self._end_ms - self._start_ms
        if not self._dragging:
            self.slider.setValue(max(0, min(duration, position - self._start_ms)))
        self.time_label.setText(
            f"{self._mmss(max(0, position - self._start_ms))} / {self._mmss(duration)}"
        )
        if position >= self._end_ms - 80 and not self._at_end:
            self._at_end = True
            self._want_play = False
            self.player.pause()

    def _state_changed(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_btn.setText("Pause" if playing else "Play")
        if playing:
            self.stack.setCurrentWidget(self.video)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._scale_poster()

    def _scale_poster(self) -> None:
        if self._poster_source.isNull() or self.stack.currentWidget() is not self.poster:
            return
        size = self.poster.size()
        if size.width() < 8 or size.height() < 8:
            return
        self.poster.setPixmap(
            self._poster_source.scaled(
                size.width() - 12,
                size.height() - 12,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )

    @staticmethod
    def _mmss(ms: int) -> str:
        seconds = max(0, int(ms / 1000))
        return f"{seconds // 60}:{seconds % 60:02d}"


class DropZone(QFrame):
    pathDropped = Signal(str)
    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(68)
        self.setCursor(Qt.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)
        title = QLabel("Drop a folder or video here")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #f5f5f7; font-weight: 500;")
        title.setAttribute(Qt.WA_TransparentForMouseEvents)
        subtitle = QLabel("or click to choose a folder or video")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setObjectName("Muted")
        subtitle.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(title)
        layout.addWidget(subtitle)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.pathDropped.emit(url.toLocalFile())
                event.acceptProposedAction()
                return


def load_app_fonts() -> None:
    global _FONTS_LOADED
    if _FONTS_LOADED:
        return
    font_dir = ASSET_DIR / "fonts"
    if not font_dir.is_dir():
        return
    for path in sorted(font_dir.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(path))
    _FONTS_LOADED = True


_FONTS_LOADED = False


def _clock(seconds: float) -> str:
    total = max(0, int(round(float(seconds))))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class HelpLabel(QLabel):
    """Small ? marker with a deliberate hover delay and generous hide grace."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__("?", parent)
        self.setObjectName("Help")
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(16, 16)
        self.setCursor(Qt.WhatsThisCursor)
        self._tooltip_text = text
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.setInterval(1000)
        self._show_timer.timeout.connect(self._really_show)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(500)
        self._hide_timer.timeout.connect(QToolTip.hideText)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hide_timer.stop()
        if not QToolTip.isVisible():
            self._show_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._show_timer.stop()
        self._hide_timer.start()
        super().leaveEvent(event)

    def _really_show(self) -> None:
        if self.underMouse() and self._tooltip_text:
            QToolTip.showText(
                self.mapToGlobal(QPoint(0, self.height() + 4)),
                self._tooltip_text,
                self,
            )

    def mousePressEvent(self, event) -> None:  # noqa: N802
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        event.accept()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        event.accept()


class ToggleSwitch(QAbstractButton):
    """Lossless Scaling-style pill switch."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(46, 24)
        self.setCursor(Qt.PointingHandCursor)
        self._offset = 0.0
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def get_offset(self) -> float:
        return self._offset

    def set_offset(self, value: float) -> None:
        self._offset = float(value)
        self.update()

    offset = Property(float, get_offset, set_offset)

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked: bool) -> None:  # noqa: N802
        super().setChecked(checked)
        self._offset = 1.0 if checked else 0.0
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(46, 24)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        checked = self.isChecked()
        track = self.rect().adjusted(1, 3, -1, -3)
        painter.setPen(QColor("#2f9bff" if checked else "#4a4a4a"))
        painter.setBrush(QColor("#2f9bff" if checked else "#343434"))
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        diameter = track.height() - 6
        x = track.left() + 3 + self._offset * (track.width() - diameter - 6)
        y = track.top() + 3
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#101010" if checked else "#d6d6d6"))
        painter.drawEllipse(int(x), int(y), diameter, diameter)
        painter.end()


class ToggleRow(QWidget):
    """Label + pill switch, with optional On/Off text."""

    toggled = Signal(bool)

    def __init__(
        self,
        title: str,
        checked: bool = False,
        parent: QWidget | None = None,
        show_state: bool = True,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.label = QLabel(title)
        self.label.setObjectName("ToggleLabel")
        self.switch = ToggleSwitch()
        self.switch.setChecked(checked)
        self.state_label: QLabel | None = None
        layout.addWidget(self.label)
        layout.addStretch(1)
        layout.addWidget(self.switch)
        if show_state:
            self.state_label = QLabel("On" if checked else "Off")
            self.state_label.setObjectName("ToggleState")
            layout.addWidget(self.state_label)
        self.switch.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool) -> None:
        if self.state_label is not None:
            self.state_label.setText("On" if checked else "Off")
        self.toggled.emit(checked)

    def isChecked(self) -> bool:  # noqa: N802
        return self.switch.isChecked()

    def setChecked(self, checked: bool) -> None:  # noqa: N802
        self.switch.setChecked(checked)
        if self.state_label is not None:
            self.state_label.setText("On" if checked else "Off")

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        super().setEnabled(enabled)
        self.label.setEnabled(enabled)
        self.switch.setEnabled(enabled)
        if self.state_label is not None:
            self.state_label.setEnabled(enabled)

    def setToolTip(self, text: str) -> None:  # noqa: N802
        super().setToolTip(text)
        self.label.setToolTip(text)
        self.switch.setToolTip(text)
        if self.state_label is not None:
            self.state_label.setToolTip(text)


class AppDialog(QDialog):
    """Small OpenCode-style modal used instead of the platform QMessageBox."""

    _ACCENTS = {
        "info": "#2f9bff",
        "warning": "#f0b35b",
        "critical": "#e05a5a",
    }

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        message: str,
        *,
        confirm: str | None = None,
        cancel: str = "Close",
        kind: str = "info",
        detail: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.setWindowTitle(title)
        self._drag_pos = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        panel = QFrame()
        panel.setObjectName("DialogPanel")
        panel.setMinimumWidth(440)
        panel.setMaximumWidth(500)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setColor(QColor(0, 0, 0, 190))
        shadow.setOffset(0, 10)
        panel.setGraphicsEffect(shadow)
        outer.addWidget(panel)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(7)
        dot = QLabel("●")
        dot.setStyleSheet(
            f"color: {self._ACCENTS.get(kind, self._ACCENTS['info'])}; font-size: 9px;"
        )
        heading = QLabel(title.upper())
        heading.setObjectName("DialogTitle")
        close = QPushButton("×")
        close.setObjectName("IconButton")
        close.setFixedSize(24, 24)
        close.clicked.connect(self.reject)
        top.addWidget(dot)
        top.addWidget(heading)
        top.addStretch(1)
        top.addWidget(close)
        layout.addLayout(top)

        body = QLabel(message)
        body.setObjectName("DialogMessage")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(body)

        if detail:
            extra = QLabel(detail)
            extra.setObjectName("Muted")
            extra.setWordWrap(True)
            extra.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(extra)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        cancel_btn = QPushButton(cancel)
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(cancel_btn)
        if confirm:
            confirm_btn = QPushButton(confirm)
            confirm_btn.setObjectName("Accent")
            confirm_btn.setDefault(True)
            confirm_btn.clicked.connect(self.accept)
            actions.addWidget(confirm_btn)
        layout.addLayout(actions)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            center = parent.window().frameGeometry().center()
            self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)


def show_message(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    kind: str = "info",
    detail: str = "",
) -> None:
    AppDialog(parent, title, message, kind=kind, detail=detail).exec()


def ask_confirm(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    confirm: str = "Continue",
    cancel: str = "Not now",
    kind: str = "info",
) -> bool:
    dialog = AppDialog(
        parent,
        title,
        message,
        confirm=confirm,
        cancel=cancel,
        kind=kind,
    )
    return dialog.exec() == QDialog.Accepted


class ClipPreviewDialog(QDialog):
    """In-app playback of one detected clip before export."""

    def __init__(
        self,
        parent: QWidget | None,
        video_path: str,
        start: float,
        end: float,
        caption: str,
        reason: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.setWindowTitle(f"Preview · {caption}")
        self.video_path = video_path
        self.start_ms = max(0, int(start * 1000))
        self.end_ms = max(self.start_ms + 250, int(end * 1000))
        self._at_end = False
        self._seeked = False
        self._dragging = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        panel = QFrame()
        panel.setObjectName("DialogPanel")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setColor(QColor(0, 0, 0, 190))
        shadow.setOffset(0, 10)
        panel.setGraphicsEffect(shadow)
        outer.addWidget(panel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        heading = QLabel("PREVIEW")
        heading.setObjectName("DialogTitle")
        top.addWidget(heading)
        self.caption_label = QLabel(caption)
        self.caption_label.setObjectName("Muted")
        top.addWidget(self.caption_label)
        top.addStretch(1)
        close = QPushButton("×")
        close.setObjectName("IconButton")
        close.setFixedSize(24, 24)
        close.clicked.connect(self.reject)
        top.addWidget(close)
        layout.addLayout(top)

        self.video = QVideoWidget()
        self.video.setMinimumHeight(430)
        layout.addWidget(self.video, 1)
        self.error_label = QLabel("")
        self.error_label.setObjectName("Muted")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.play_btn = QPushButton("Play")
        self.play_btn.setFixedWidth(74)
        self.play_btn.clicked.connect(self._toggle_play)
        controls.addWidget(self.play_btn)
        back_btn = QPushButton("−5s")
        back_btn.setFixedWidth(54)
        back_btn.clicked.connect(lambda: self._seek_relative(-5000))
        controls.addWidget(back_btn)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, max(1, self.end_ms - self.start_ms))
        self.slider.sliderPressed.connect(self._slider_pressed)
        self.slider.sliderReleased.connect(self._slider_released)
        self.slider.sliderMoved.connect(self._slider_moved)
        controls.addWidget(self.slider, 1)
        ahead_btn = QPushButton("+5s")
        ahead_btn.setFixedWidth(54)
        ahead_btn.clicked.connect(lambda: self._seek_relative(5000))
        controls.addWidget(ahead_btn)
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setObjectName("PreviewTime")
        self.time_label.setMinimumWidth(96)
        controls.addWidget(self.time_label)
        open_btn = QPushButton("Open")
        open_btn.setToolTip("Open the source video in the default player")
        open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.video_path))
        )
        controls.addWidget(open_btn)
        layout.addLayout(controls)

        if reason:
            reason_label = QLabel(reason)
            reason_label.setObjectName("Muted")
            reason_label.setWordWrap(True)
            layout.addWidget(reason_label)

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.85)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self._position_changed)
        self.player.playbackStateChanged.connect(self._state_changed)
        self.player.mediaStatusChanged.connect(self._media_status)
        self.player.errorOccurred.connect(self._player_error)
        self.player.setSource(QUrl.fromLocalFile(str(Path(video_path))))

        self.resize(1000, 680)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        parent = self.parentWidget()
        if parent is not None:
            center = parent.window().frameGeometry().center()
            self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)

    def _media_status(self, status) -> None:
        if status in {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        } and not self._seeked:
            self._seeked = True
            self.player.setPosition(self.start_ms)
            self.player.play()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._player_error(None, "This video codec cannot be previewed here.")

    def _player_error(self, error, message: str) -> None:
        self.error_label.setText(
            f"Preview unavailable: {message or 'codec not supported'}. "
            "Use Open to play the source file."
        )
        self.error_label.show()

    def _toggle_play(self) -> None:
        if self._at_end:
            self._at_end = False
            self.player.setPosition(self.start_ms)
            self.player.play()
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            if self.player.position() < self.start_ms or self.player.position() >= self.end_ms:
                self.player.setPosition(self.start_ms)
            self.player.play()

    def _seek_relative(self, delta_ms: int) -> None:
        position = self.player.position() + delta_ms
        position = max(self.start_ms, min(self.end_ms - 100, position))
        self._at_end = False
        self.player.setPosition(position)

    def _slider_pressed(self) -> None:
        self._dragging = True

    def _slider_released(self) -> None:
        self._dragging = False
        self._at_end = False
        self.player.setPosition(self.start_ms + self.slider.value())

    def _slider_moved(self, value: int) -> None:
        self._at_end = False
        self.player.setPosition(self.start_ms + value)

    def _position_changed(self, position: int) -> None:
        if not self._seeked:
            return
        if not self._dragging:
            self.slider.setValue(max(0, min(self.end_ms - self.start_ms, position - self.start_ms)))
        self.time_label.setText(
            f"{self._mmss(max(0, position - self.start_ms))} / "
            f"{self._mmss(self.end_ms - self.start_ms)}"
        )
        if position >= self.end_ms - 80 and not self._at_end:
            self._at_end = True
            self.player.pause()

    def _state_changed(self, state) -> None:
        self.play_btn.setText(
            "Pause" if state == QMediaPlayer.PlaybackState.PlayingState else "Play"
        )

    @staticmethod
    def _mmss(ms: int) -> str:
        seconds = max(0, int(ms / 1000))
        return f"{seconds // 60}:{seconds % 60:02d}"

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        if event.key() == Qt.Key_Space:
            self._toggle_play()
            return
        super().keyPressEvent(event)

    def reject(self) -> None:  # noqa: N802
        self._release_media()
        super().reject()

    def _release_media(self) -> None:
        self.player.stop()
        self.player.setSource(QUrl())

    def closeEvent(self, event) -> None:  # noqa: N802
        self._release_media()
        super().closeEvent(event)



class MainWindow(QMainWindow):
    def __init__(self, initial_input: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle(f"Clipper {__version__}")
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.resize(1280, 840)
        self.setMinimumSize(1040, 720)
        if VIDEO_ICON.is_file():
            self.setWindowIcon(QIcon(str(VIDEO_ICON)))

        self.qsettings = QSettings("hatermedia", "Clipper")
        load_app_fonts()
        self.summary: AnalysisSummary | None = None
        self._live_done = 0
        self._live_total = 0
        self._live_clips = 0
        self.worker: AnalyzeWorker | None = None
        self.export_worker: ExportWorker | None = None
        self._update_shutdown = False
        self.preview_dir = Path(tempfile.mkdtemp(prefix="clipper-desktop-"))
        self.files: list[Path] = []
        self.last_output_dir: str | None = None
        self.nvenc = False
        self._screenshot_path: Path | None = None
        ai_state = ollama_status(timeout=1.5)
        self.ollama_ok = bool(ai_state.get("ok"))
        self.ollama_present = ollama_executable() is not None
        installed = {str(name).lower(): str(name) for name in ai_state.get("models", [])}
        self.installed_models = installed
        vision = [
            name for name in installed.values()
            if any(token in name.lower() for token in ("vl", "llava", "minicpm", "moondream", "gemma3"))
            and not name.lower().startswith("qwen3")
            and "qwen2.5vl:3b" not in name.lower()
        ]
        self.ai_models = vision
        self.vlm_available = bool(vision)
        self.ai_available = True
        self.ai_default = DEFAULT_MODEL if DEFAULT_MODEL.lower() in installed else (vision[0] if vision else "No VLM installed (Lite mode)")
        self.gpu_vram_mb = nvidia_memory_mb()
        self.low_vram = bool(self.gpu_vram_mb and self.gpu_vram_mb <= 7000)
        if self.low_vram and "gemma3:4b" in installed:
            self.ai_default = "gemma3:4b"
        self._detected_game: str | None = None
        self.update_release: ReleaseInfo | None = None
        self.update_installer: Path | None = None
        self.update_check_worker: UpdateCheckWorker | None = None
        self.update_download_worker: UpdateDownloadWorker | None = None
        self.pull_worker: OllamaPullWorker | None = None
        self.ai_install_worker: OllamaInstallWorker | None = None
        self._manual_update_check = False
        self._job_running = False

        try:
            bins = find_ffmpeg()
            self.ffmpeg_ok = True
            self.ffmpeg_text = ffmpeg_version(bins)
            self.nvenc = nvenc_available(bins)
        except Exception:
            self.ffmpeg_ok = False
            self.ffmpeg_text = "FFmpeg not found"
            self.nvenc = False

        self._build_ui()
        self._restore_settings()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(18, 18)
        self.size_grip.setToolTip("Drag to resize")
        self._position_size_grip()
        if initial_input:
            self.set_input(initial_input, scan=False)
        self._update_status()
        QTimer.singleShot(2500, lambda: self.check_updates(manual=False))
        self.game_timer = QTimer(self)
        self.game_timer.timeout.connect(self._poll_game)
        self.game_timer.start(5000)
        QTimer.singleShot(400, self._poll_game)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        titlebar = QWidget()
        titlebar.setObjectName("TitleBar")
        header = QHBoxLayout(titlebar)
        header.setContentsMargins(18, 8, 0, 8)
        header.setSpacing(10)
        self._header_layout = header
        logo = QLabel()
        if VIDEO_ICON.is_file():
            pix = QPixmap(str(VIDEO_ICON)).scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo.setPixmap(pix)
        header.addWidget(logo)
        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)
        brand_line = QHBoxLayout()
        brand_line.setSpacing(8)
        brand = QLabel("CLIPPER")
        brand.setObjectName("Brand")
        version_label = QLabel(f"v{__version__}")
        version_label.setObjectName("BrandSub")
        brand_line.addWidget(brand)
        brand_line.addWidget(version_label)
        brand_line.addStretch(1)
        sub = QLabel("local highlight engine")
        sub.setObjectName("BrandSub")
        brand_box.addLayout(brand_line)
        brand_box.addWidget(sub)
        header.addLayout(brand_box)
        header.addStretch(1)
        self.gpu_label = QLabel("nvenc / checking")
        self.gpu_label.setObjectName("Status")
        self.ffmpeg_label = QLabel("ffmpeg / checking")
        self.ffmpeg_label.setObjectName("Status")
        header.addWidget(self.ffmpeg_label)
        header.addWidget(self.gpu_label)
        updates = QPushButton("Updates")
        updates.setObjectName("Mono")
        updates.setToolTip("Check GitHub for a newer Clipper release")
        updates.clicked.connect(lambda: self.check_updates(manual=True))
        header.addWidget(updates)
        github = QPushButton("GitHub ↗")
        github.setObjectName("Mono")
        github.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://github.com/hatermedia/clipper"))
        )
        header.addWidget(github)
        header.addSpacing(6)

        minimize = QPushButton()
        minimize.setObjectName("WindowButton")
        minimize.setFixedSize(46, 32)
        minimize.setIcon(_window_icon("min"))
        minimize.setIconSize(QSize(16, 16))
        minimize.clicked.connect(self.showMinimized)
        header.addWidget(minimize)

        self.max_btn = QPushButton()
        self.max_btn.setObjectName("WindowButton")
        self.max_btn.setFixedSize(46, 32)
        self.max_btn.setIcon(_window_icon("max"))
        self.max_btn.setIconSize(QSize(16, 16))
        self.max_btn.clicked.connect(self._toggle_maximize)
        header.addWidget(self.max_btn)

        close = QPushButton()
        close.setObjectName("WindowClose")
        close.setFixedSize(46, 32)
        close.setIcon(_window_icon("close"))
        close.setIconSize(QSize(16, 16))
        close.clicked.connect(self.close)
        header.addWidget(close)
        outer.addWidget(titlebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 0, 18, 16)
        content_layout.setSpacing(12)
        outer.addWidget(content, 1)

        self.update_bar = QFrame()
        self.update_bar.setObjectName("UpdateBar")
        update_row = QHBoxLayout(self.update_bar)
        update_row.setContentsMargins(12, 7, 8, 7)
        update_row.setSpacing(8)
        self.update_label = QLabel("")
        update_row.addWidget(self.update_label, 1)
        self.update_action = QPushButton("Download update")
        self.update_action.setObjectName("Accent")
        self.update_action.clicked.connect(self._update_action_clicked)
        update_row.addWidget(self.update_action)
        update_later = QPushButton("Later")
        update_later.clicked.connect(self.update_bar.hide)
        update_row.addWidget(update_later)
        self.update_bar.hide()
        content_layout.addWidget(self.update_bar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        content_layout.addWidget(splitter, 1)

        # ---------------- left controls ----------------
        left_panel = QFrame()
        left_panel.setObjectName("Panel")
        left_panel.setMinimumWidth(420)
        left_panel.setMaximumWidth(460)
        left_shell = QVBoxLayout(left_panel)
        left_shell.setContentsMargins(0, 0, 0, 0)
        left_shell.setSpacing(0)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        controls = QWidget()
        left = QVBoxLayout(controls)
        left.setContentsMargins(16, 14, 16, 8)
        left.setSpacing(7)

        left.addWidget(self._section("Footage"))
        path_row = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("No folder selected")
        self.input_edit.editingFinished.connect(lambda: self.set_input(self.input_edit.text(), scan=False))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.choose_input)
        path_row.addWidget(self.input_edit, 1)
        path_row.addWidget(browse)
        left.addLayout(path_row)

        self.drop = DropZone()
        self.drop.setFixedHeight(88)
        self.drop.pathDropped.connect(lambda p: self.set_input(p, scan=True))
        self.drop.clicked.connect(self.choose_input)
        left.addWidget(self.drop)

        row = QHBoxLayout()
        self.recursive = ToggleRow("Include subfolders")
        row.addWidget(self.recursive)
        row.addStretch(1)
        self.scan_btn = QPushButton("Scan")
        self.scan_btn.clicked.connect(self.scan)
        row.addWidget(self.scan_btn)
        left.addLayout(row)

        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(76)
        self.file_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.file_list.setVisible(False)
        left.addWidget(self.file_list)

        left.addSpacing(6)
        detection_header = QHBoxLayout()
        detection_header.addWidget(self._section("Detection"))
        detection_header.addStretch(1)
        self.advanced_toggle = QPushButton("Advanced  ▾")
        self.advanced_toggle.setObjectName("Mono")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setToolTip(
            "Max clips, sample rate, proxy size, CPU cap, pre/post-roll, and low-power mode."
        )
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        detection_header.addWidget(self.advanced_toggle)
        left.addLayout(detection_header)
        sensitivity_row = QHBoxLayout()
        sensitivity_row.addWidget(QLabel("Sensitivity"))
        sensitivity_row.addStretch(1)
        self.sensitivity_value = QLabel("50%")
        self.sensitivity_value.setObjectName("Status")
        sensitivity_row.addWidget(self.sensitivity_value)
        sensitivity_row.addWidget(
            self._help(
                "Higher sensitivity finds more moments; lower is stricter. "
                "The director uses this as its keep threshold too."
            )
        )
        left.addLayout(sensitivity_row)
        self.sensitivity = QSlider(Qt.Horizontal)
        self.sensitivity.setRange(0, 100)
        self.sensitivity.setValue(50)
        self.sensitivity.valueChanged.connect(self._sensitivity_changed)
        left.addWidget(self.sensitivity)

        presets = QHBoxLayout()
        self.preset_group = QButtonGroup(self)
        self.preset_group.setExclusive(True)
        self.preset_buttons: list[tuple[QPushButton, int]] = []
        for label, value, tip in (
            ("Strict", 32, "Fewer clips, higher confidence."),
            ("Balanced", 50, "The default mix of recall and precision."),
            ("Loose", 78, "More clips; expect more false positives."),
        ):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setObjectName("Preset")
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, v=value: self.sensitivity.setValue(v))
            self.preset_group.addButton(button)
            self.preset_buttons.append((button, value))
            presets.addWidget(button)
        left.addLayout(presets)
        self._sensitivity_changed(self.sensitivity.value())

        ai_row = QHBoxLayout()
        self.ai = ToggleRow("AI director (local)")
        self.ai.setToolTip(
            "The local AI watches the whole clip with audio and sampled frames, "
            "then keeps the funny interactions, banter, reactions, and big plays."
        )
        self.ai_state = self.ai.state_label
        ai_row.addWidget(self.ai)
        ai_row.addWidget(
            self._help(
                "The local AI director transcribes the clip with Whisper, watches every window, "
                "and keeps funny interactions, banter, reactions, goals, and big plays. "
                "It runs locally; nothing is uploaded."
            )
        )
        ai_row.addStretch(1)
        left.addLayout(ai_row)

        ai_controls = QGridLayout()
        ai_controls.setHorizontalSpacing(8)
        ai_controls.setVerticalSpacing(3)
        ai_controls.setColumnStretch(1, 1)
        ai_controls.addWidget(QLabel("AI model"), 0, 0)
        self.ai_model = QComboBox()
        for model in (self.ai_models or [self.ai_default]):
            self.ai_model.addItem(model)
        preferred = self.ai_model.findText(self.ai_default)
        if preferred >= 0:
            self.ai_model.setCurrentIndex(preferred)
        self.ai_model.setEnabled(self.vlm_available)
        if self.low_vram:
            self.ai_model.setToolTip(
                f"{self.gpu_vram_mb} MB VRAM detected. Lite mode is recommended. "
                "gemma3:4b is tested on 6 GB cards; qwen2.5vl:7b is best on 8 GB+."
            )
        elif not self.vlm_available:
            self.ai_model.setToolTip(
                "No Ollama vision model detected. Lite mode works without one."
            )
        ai_controls.addWidget(self.ai_model, 0, 1)
        ai_controls.addWidget(
            self._help(
                "Lite needs no model. gemma3:4b is tested on 6 GB cards; "
                "qwen2.5vl:7b is the better choice on 8 GB+."
            ),
            0,
            2,
        )
        ai_controls.addWidget(QLabel("Game"), 1, 0)
        self.ai_game = QComboBox()
        for label, value in (
            ("Auto (from folder)", "auto"),
            ("Valorant", "Valorant"),
            ("Apex Legends", "Apex Legends"),
            ("CS2", "Counter-Strike 2"),
            ("Rocket League", "Rocket League"),
            ("Mimesis", "Mimesis"),
            ("Generic", "generic"),
        ):
            self.ai_game.addItem(label, value)
        self.ai_game.setCurrentIndex(0)
        ai_controls.addWidget(self.ai_game, 1, 1)
        ai_controls.addWidget(
            self._help(
                "Auto reads the game from each file's folder or name, so one NVIDIA parent folder "
                "can contain Rocket League, Mimesis, Valorant, etc. Pick a preset to override it."
            ),
            1,
            2,
        )
        ai_controls.addWidget(QLabel("AI mode"), 2, 0)
        self.ai_mode = QComboBox()
        self.ai_mode.addItem("Director · whole clip", "director")
        self.ai_mode.addItem("Lite · OCR + signals", "lite")
        self.ai_mode.addItem("Fast review · legacy", "review")
        self.ai_mode.setToolTip(
            "Director watches the whole clip with a local vision model. "
            "Lite uses HUD OCR, Whisper, and audio/motion signals with no VLM (best for 6 GB cards). "
            "Fast review is the older peak-only pass."
        )
        ai_controls.addWidget(self.ai_mode, 2, 1)
        ai_controls.addWidget(
            self._help(
                "Director: whole-clip audio + frame review, can keep a 30-45s interaction. "
                "Lite: HUD OCR + transcript + acoustic/motion signals, no VLM or extra VRAM. "
                "Fast review: legacy peak-only pass."
            ),
            2,
            2,
        )
        left.addLayout(ai_controls)

        self.ai_setup = QFrame()
        self.ai_setup.setObjectName("AiSetup")
        setup_layout = QVBoxLayout(self.ai_setup)
        setup_layout.setContentsMargins(10, 8, 10, 8)
        setup_layout.setSpacing(4)
        self.ai_setup_title = QLabel("Lite mode is ready")
        self.ai_setup_title.setObjectName("AiSetupTitle")
        setup_layout.addWidget(self.ai_setup_title)
        self.ai_setup_text = QLabel("")
        self.ai_setup_text.setObjectName("Muted")
        self.ai_setup_text.setWordWrap(True)
        setup_layout.addWidget(self.ai_setup_text)
        self.ai_setup_status = QLabel("")
        self.ai_setup_status.setObjectName("Muted")
        self.ai_setup_status.setWordWrap(True)
        self.ai_setup_status.hide()
        setup_layout.addWidget(self.ai_setup_status)
        setup_actions = QHBoxLayout()
        setup_actions.setSpacing(6)
        self.get_ollama_btn = QPushButton("Install Ollama")
        self.get_ollama_btn.setObjectName("Mono")
        self.get_ollama_btn.setToolTip(
            "Download the official Ollama installer, verify it, and install it "
            "for this Windows user. The AI model is downloaded separately."
        )
        self.get_ollama_btn.clicked.connect(self._install_ollama)
        setup_actions.addWidget(self.get_ollama_btn)
        self.refresh_ai_btn = QPushButton("Refresh")
        self.refresh_ai_btn.setObjectName("Mono")
        self.refresh_ai_btn.clicked.connect(self._refresh_ai_models)
        setup_actions.addWidget(self.refresh_ai_btn)
        self.pull_ai_btn = QPushButton("Install model")
        self.pull_ai_btn.setObjectName("Mono")
        self.pull_ai_btn.clicked.connect(self._pull_ai_model)
        setup_actions.addWidget(self.pull_ai_btn)
        self.cancel_ai_btn = QPushButton("Cancel")
        self.cancel_ai_btn.setObjectName("Mono")
        self.cancel_ai_btn.clicked.connect(self._cancel_ollama_install)
        self.cancel_ai_btn.hide()
        setup_actions.addWidget(self.cancel_ai_btn)
        setup_actions.addStretch(1)
        setup_layout.addLayout(setup_actions)
        self.ai_setup_progress = QProgressBar()
        self.ai_setup_progress.setRange(0, 1000)
        self.ai_setup_progress.setTextVisible(False)
        self.ai_setup_progress.setFixedHeight(5)
        self.ai_setup_progress.hide()
        setup_layout.addWidget(self.ai_setup_progress)
        left.addWidget(self.ai_setup)
        self._update_ai_setup()
        self.ai.setEnabled(self.ai_available)

        game_row = QHBoxLayout()
        self.game_guard = ToggleRow("Pause AI while gaming", show_state=False)
        self.game_guard.setChecked(True)
        self.game_guard.setToolTip(
            "Pause AI and free VRAM while a game is running."
        )
        game_row.addWidget(self.game_guard)
        game_row.addWidget(
            self._help(
                "Uses the local process list, not Discord presence.\n"
                "Pauses analysis and unloads the vision model while a game runs."
            )
        )
        game_row.addStretch(1)
        left.addLayout(game_row)

        gpu_row = QHBoxLayout()
        self.gpu = ToggleRow("Use NVIDIA GPU (NVENC)")
        self.gpu.setToolTip(
            "Hardware decode + NVENC for the analysis proxy and re-encode. "
            "OpenCV motion scoring and audio analysis stay on the CPU."
        )
        self.gpu_state = self.gpu.state_label
        gpu_row.addWidget(self.gpu)
        gpu_row.addWidget(
            self._help(
                "NVENC handles proxy encode and optional re-encode. OpenCV motion scoring "
                "and audio RMS stay on the CPU."
            )
        )
        gpu_row.addStretch(1)
        self.gpu_row = gpu_row
        self.gpu.setEnabled(self.nvenc)

        self.advanced = QFrame()
        advanced_layout = QGridLayout(self.advanced)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setHorizontalSpacing(8)
        advanced_layout.setVerticalSpacing(7)

        def advanced_label(text: str, tip: str) -> QHBoxLayout:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            row.addWidget(QLabel(text))
            row.addWidget(self._help(tip))
            row.addStretch(1)
            return row

        advanced_layout.addLayout(
            advanced_label(
                "Max clips",
                "Maximum number of highlights kept per video. Lower it for a short reel.",
            ),
            0,
            0,
        )
        self.max_clips = QSpinBox()
        self.max_clips.setRange(1, 200)
        self.max_clips.setValue(30)
        self.max_clips.setToolTip("Maximum highlights kept per video.")
        advanced_layout.addWidget(self.max_clips, 0, 1)
        advanced_layout.addLayout(
            advanced_label(
                "Sample FPS",
                "How many frames per second the visual detector checks. Higher catches "
                "faster flashes but uses more CPU.",
            ),
            1,
            0,
        )
        self.sample_fps = QComboBox()
        for label, value in (("2 fps", 2.0), ("4 fps", 4.0), ("8 fps", 8.0)):
            self.sample_fps.addItem(label, value)
        self.sample_fps.setCurrentIndex(1)
        self.sample_fps.setToolTip("Visual sampling rate for detection.")
        advanced_layout.addWidget(self.sample_fps, 1, 1)
        advanced_layout.addLayout(
            advanced_label(
                "Proxy width",
                "Width of the low-resolution copy used for motion scoring. Higher is "
                "more accurate; lower is faster.",
            ),
            2,
            0,
        )
        self.proxy_width = QComboBox()
        for label, value in (("256 px", 256), ("320 px", 320), ("480 px", 480)):
            self.proxy_width.addItem(label, value)
        self.proxy_width.setCurrentIndex(1)
        self.proxy_width.setToolTip("Resolution of the analysis-only proxy.")
        advanced_layout.addWidget(self.proxy_width, 2, 1)
        advanced_layout.addLayout(
            advanced_label(
                "CPU threads",
                "Threads used by FFmpeg and the detectors. Balanced uses about half "
                "the cores; Low uses two; Max lets FFmpeg decide.",
            ),
            3,
            0,
        )
        self.threads = QComboBox()
        self.threads.addItem("Balanced", default_threads())
        self.threads.addItem("Low (2)", 2)
        self.threads.addItem("Max (all)", 0)
        self.threads.setToolTip("CPU thread cap for analysis and export.")
        advanced_layout.addWidget(self.threads, 3, 1)
        pre_labels = QHBoxLayout()
        pre_labels.addWidget(QLabel("Pre-roll (s)"))
        pre_labels.addWidget(
            self._help("Seconds kept before a detected peak. The director trims conversations to the spoken exchange.")
        )
        pre_labels.addStretch(1)
        advanced_layout.addLayout(pre_labels, 4, 0)
        post_labels = QHBoxLayout()
        post_labels.addWidget(QLabel("Post-roll (s)"))
        post_labels.addWidget(
            self._help("Seconds kept after a detected peak. The director uses story boundaries for long interactions.")
        )
        post_labels.addStretch(1)
        advanced_layout.addLayout(post_labels, 4, 1)
        self.pre = QSpinBox()
        self.pre.setRange(0, 120)
        self.pre.setValue(8)
        self.post = QSpinBox()
        self.post.setRange(0, 120)
        self.post.setValue(5)
        advanced_layout.addWidget(self.pre, 5, 0)
        advanced_layout.addWidget(self.post, 5, 1)
        advanced_layout.addLayout(self.gpu_row, 6, 0, 1, 2)
        self.low_power = ToggleRow("Low-power mode")
        self.low_power.setToolTip(
            "Performance preset: 2 threads, 256px/2fps analysis proxy, below-normal "
            "process priority.\nAI Director still runs if enabled."
        )
        low_row = QHBoxLayout()
        low_row.setContentsMargins(0, 0, 0, 0)
        low_row.setSpacing(4)
        low_row.addWidget(self.low_power)
        low_row.addWidget(
            self._help(
                "Reduces CPU and proxy cost. It does not disable AI; turn off "
                "AI Director separately if you want heuristic-only detection."
            )
        )
        low_row.addStretch(1)
        advanced_layout.addLayout(low_row, 7, 0, 1, 2)
        advanced_layout.addWidget(
            QLabel("GPU helps decode/encode; motion scoring remains CPU-bound."),
            8, 0, 1, 2,
        )
        self.advanced.setVisible(False)
        left.addWidget(self.advanced)
        left.addStretch(1)

        left_scroll.setWidget(controls)
        left_shell.addWidget(left_scroll, 1)

        footer = QFrame()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(16, 8, 16, 16)
        footer_layout.setSpacing(7)
        self.analyze_btn = QPushButton("Detect highlights")
        self.analyze_btn.setObjectName("Primary")
        self.analyze_btn.clicked.connect(self.analyze)
        footer_layout.addWidget(self.analyze_btn)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        footer_layout.addWidget(self.progress)
        self.status = QLabel("ready")
        self.status.setObjectName("Status")
        self.status.setWordWrap(True)
        footer_layout.addWidget(self.status)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_current)
        footer_layout.addWidget(self.cancel_btn)
        left_shell.addWidget(footer)

        splitter.addWidget(left_panel)

        # ---------------- right results ----------------
        right_panel = QFrame()
        right_panel.setObjectName("Panel")
        right = QVBoxLayout(right_panel)
        right.setContentsMargins(16, 16, 16, 16)
        right.setSpacing(10)

        results_header = QHBoxLayout()
        results_header.addWidget(self._section("Highlights"))
        results_header.addStretch(1)
        self.select_all_btn = QPushButton("Select all")
        self.select_all_btn.setObjectName("Mono")
        self.select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        self.select_all_btn.hide()
        results_header.addWidget(self.select_all_btn)
        self.select_none_btn = QPushButton("None")
        self.select_none_btn.setObjectName("Mono")
        self.select_none_btn.clicked.connect(lambda: self._set_all_checked(False))
        self.select_none_btn.hide()
        results_header.addWidget(self.select_none_btn)
        self.summary_label = QLabel("Nothing analyzed yet")
        self.summary_label.setObjectName("Summary")
        results_header.addWidget(self.summary_label)
        right.addLayout(results_header)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(7)
        self.tree.setHeaderLabels(
            ["Keep", "Video", "Start", "End", "Length", "Score", "Why"]
        )
        header = self.tree.headerItem()
        header.setTextAlignment(0, Qt.AlignCenter)
        header.setTextAlignment(5, Qt.AlignCenter)
        header.setToolTip(0, "Toggle a clip to include it in the export.")
        header.setToolTip(1, "Source video. Select a row to preview it below.")
        header.setToolTip(5, "AI confidence blended with the audio/motion score.")
        header.setToolTip(6, "Grounded reason: verified HUD text, a transcript quote, or a chat line.")
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Fixed)
        self.tree.setColumnWidth(0, 92)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Interactive)
        self.tree.setColumnWidth(1, 190)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(6, QHeaderView.Stretch)
        self.tree.currentItemChanged.connect(self._show_preview)
        self.tree.itemDoubleClicked.connect(self._tree_double_clicked)
        self.tree.itemChanged.connect(self._clip_check_changed)
        right.addWidget(self.tree, 1)

        self.preview_player = InlineClipPreview()
        right.addWidget(self.preview_player)

        export_group = QGroupBox("Export")
        export_layout = QGridLayout(export_group)
        export_layout.setHorizontalSpacing(8)
        export_layout.setVerticalSpacing(7)
        output_label = QHBoxLayout()
        output_label.setContentsMargins(0, 0, 0, 0)
        output_label.setSpacing(4)
        output_label.addWidget(QLabel("Output"))
        output_label.addWidget(
            self._help("Folder where exported highlight files are written.")
        )
        output_label.addStretch(1)
        export_layout.addLayout(output_label, 0, 0)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Choose an output folder")
        self.output_edit.setToolTip("Folder where exported highlight files are written.")
        export_layout.addWidget(self.output_edit, 0, 1)
        out_browse = QPushButton("Browse…")
        out_browse.clicked.connect(self.choose_output)
        export_layout.addWidget(out_browse, 0, 2)
        self.reencode = ToggleRow("Frame-accurate re-encode")
        self.reencode.setToolTip(
            "Off: stream copy, nearly instant and lossless, but cuts start on the "
            "nearest keyframe.\nOn: re-encode for exact cut edges, slower and uses "
            "more CPU/GPU."
        )
        self.reencode.toggled.connect(self._update_encoder_state)
        reencode_row = QHBoxLayout()
        reencode_row.setContentsMargins(0, 0, 0, 0)
        reencode_row.setSpacing(4)
        reencode_row.addWidget(self.reencode)
        reencode_row.addWidget(
            self._help(
                "Stream copy is faster and preserves the original video stream. "
                "Frame-accurate re-encode is slower but cuts exactly at the requested second."
            )
        )
        reencode_row.addStretch(1)
        export_layout.addLayout(reencode_row, 1, 0, 1, 2)
        self.encoder = QComboBox()
        for label, value in (
            ("Auto", "auto"),
            ("libx264 (CPU)", "libx264"),
            ("H.264 NVENC", "h264_nvenc"),
            ("HEVC NVENC", "hevc_nvenc"),
            ("libx265 (CPU)", "libx265"),
        ):
            self.encoder.addItem(label, value)
        self.encoder.setToolTip(
            "Encoder for frame-accurate re-encode. Auto prefers NVENC when it works, "
            "then falls back to CPU."
        )
        self.encoder.currentIndexChanged.connect(self._encoder_changed)
        export_layout.addWidget(self.encoder, 1, 2)
        crf_label = QHBoxLayout()
        crf_label.setContentsMargins(0, 0, 0, 0)
        crf_label.setSpacing(4)
        crf_label.addWidget(QLabel("CRF"))
        crf_label.addWidget(
            self._help(
                "Quality for re-encode. Lower is higher quality and larger files. "
                "Auto uses 20; set 0 in the spinner to return to Auto."
            )
        )
        crf_label.addStretch(1)
        export_layout.addLayout(crf_label, 2, 0)
        self.crf = QSpinBox()
        self.crf.setRange(0, 51)
        self.crf.setValue(0)
        self.crf.setSpecialValueText("Auto")
        self.crf.setToolTip(
            "Auto uses CRF 20. Lower values (18) are higher quality; higher values "
            "(23–28) make smaller files."
        )
        export_layout.addWidget(self.crf, 2, 1)
        export_actions = QHBoxLayout()
        export_actions.setSpacing(6)
        self.export_all_btn = QPushButton("Export all")
        self.export_all_btn.setToolTip("Export every detected clip.")
        self.export_all_btn.clicked.connect(lambda: self.export(selected_only=False))
        self.export_all_btn.setEnabled(False)
        export_actions.addWidget(self.export_all_btn)
        self.export_btn = QPushButton("Export selected")
        self.export_btn.setObjectName("Primary")
        self.export_btn.setToolTip("Export only the checked clips.")
        self.export_btn.clicked.connect(lambda: self.export(selected_only=True))
        self.export_btn.setEnabled(False)
        export_actions.addWidget(self.export_btn)
        export_layout.addLayout(export_actions, 2, 2)
        right.addWidget(export_group)

        export_footer = QHBoxLayout()
        self.selection_label = QLabel("")
        self.selection_label.setObjectName("Muted")
        export_footer.addWidget(self.selection_label)
        self.export_status = QLabel("")
        self.export_status.setObjectName("Status")
        self.export_status.setWordWrap(True)
        export_footer.addWidget(self.export_status, 1)
        self.open_folder = QPushButton("Open folder")
        self.open_folder.setEnabled(False)
        self.open_folder.clicked.connect(self.open_output)
        export_footer.addWidget(self.open_folder)
        right.addLayout(export_footer)

        splitter.addWidget(right_panel)
        splitter.setSizes([430, 826])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        self._update_encoder_state()

    def _section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Section")
        return label

    def _help(self, text: str) -> QLabel:
        return HelpLabel(text)

    # ------------------------------------------------------------- settings
    def _restore_settings(self) -> None:
        self.sensitivity.setValue(int(self.qsettings.value("sensitivity", 50)))
        self.pre.setValue(int(self.qsettings.value("pre", 8)))
        self.post.setValue(int(self.qsettings.value("post", 5)))
        self.recursive.setChecked(self.qsettings.value("recursive", "false") in (True, "true"))
        # New key so the old "off by default" setting does not stick after upgrade.
        if self.qsettings.contains("gpu_v2"):
            gpu_default = self.qsettings.value("gpu_v2", "false") in (True, "true")
        else:
            gpu_default = self.nvenc
        self.gpu.setChecked(bool(gpu_default) and self.nvenc)
        self.low_power.setChecked(self.qsettings.value("low_power", "false") in (True, "true"))
        self.low_power.toggled.connect(self._low_power_changed)
        self.gpu.toggled.connect(self._gpu_changed)
        self.gpu.setEnabled(self.nvenc)
        self._gpu_changed(self.gpu.isChecked())

        if self.ai_available:
            if self.qsettings.contains("ai_v2"):
                ai_default = self.qsettings.value("ai_v2", "false") in (True, "true")
            else:
                ai_default = True
            self.ai.setChecked(bool(ai_default))
            stored_model = str(self.qsettings.value("ai_model", ""))
            if stored_model and self.ai_model.findText(stored_model) >= 0 and self.vlm_available:
                self.ai_model.setCurrentText(stored_model)
            stored_game = str(self.qsettings.value("ai_game", ""))
            if stored_game:
                game_index = self.ai_game.findData(stored_game)
                if game_index >= 0:
                    self.ai_game.setCurrentIndex(game_index)
            default_mode = "lite" if (self.low_vram or not self.vlm_available) else "director"
            stored_mode = str(self.qsettings.value("ai_mode", default_mode))
            if not self.vlm_available and stored_mode in {"director", "review"}:
                stored_mode = "lite"
            mode_index = self.ai_mode.findData(stored_mode)
            if mode_index >= 0:
                self.ai_mode.setCurrentIndex(mode_index)
        else:
            self.ai.setChecked(False)
        guard_default = self.qsettings.value("game_guard", "true") in (True, "true")
        self.game_guard.setChecked(bool(guard_default))
        self.game_guard.toggled.connect(lambda _: self._poll_game())
        self.ai.toggled.connect(self._ai_changed)
        self.ai_model.currentTextChanged.connect(lambda _: self._ai_changed(self.ai.isChecked()))
        self.ai_mode.currentIndexChanged.connect(lambda _: self._ai_changed(self.ai.isChecked()))
        self._ai_changed(self.ai.isChecked())
        self.input_edit.setText(str(self.qsettings.value("input", "")))
        self.input_edit.setCursorPosition(0)
        self.output_edit.setText(str(self.qsettings.value("output", "")))
        self.output_edit.setCursorPosition(0)
        geometry = self.qsettings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        self._clamp_to_screen()
        if self.low_power.isChecked():
            self.threads.setCurrentIndex(1)
            self.threads.setEnabled(False)
        self._update_status()

    def _save_settings(self) -> None:
        self.qsettings.setValue("sensitivity", self.sensitivity.value())
        self.qsettings.setValue("pre", self.pre.value())
        self.qsettings.setValue("post", self.post.value())
        self.qsettings.setValue("recursive", self.recursive.isChecked())
        self.qsettings.setValue("gpu_v2", self.gpu.isChecked())
        if self.ai_available:
            self.qsettings.setValue("ai_v2", self.ai.isChecked())
        self.qsettings.setValue("ai_model", self.ai_model.currentText())
        self.qsettings.setValue("ai_game", str(self.ai_game.currentData()))
        self.qsettings.setValue("ai_mode", str(self.ai_mode.currentData()))
        self.qsettings.setValue("game_guard", self.game_guard.isChecked())
        self.qsettings.setValue("low_power", self.low_power.isChecked())
        self.qsettings.setValue("input", self.input_edit.text())
        self.qsettings.setValue("output", self.output_edit.text())
        self.qsettings.setValue("geometry", self.saveGeometry())

    # --------------------------------------------------------------- updates
    def check_updates(self, manual: bool = False) -> None:
        if self.update_check_worker is not None and self.update_check_worker.isRunning():
            return
        self._manual_update_check = manual
        if manual:
            self.update_label.setText("Checking GitHub for updates…")
            self.update_action.setText("Checking…")
            self.update_action.setEnabled(False)
            self.update_bar.show()
        worker = UpdateCheckWorker(force=manual)
        worker.found.connect(self._update_found)
        worker.failed.connect(self._update_check_failed)
        worker.finished.connect(worker.deleteLater)
        self.update_check_worker = worker
        worker.start()

    def _update_found(self, release: object) -> None:
        self.update_check_worker = None
        if release is None:
            self.update_bar.hide()
            if self._manual_update_check:
                show_message(
                    self,
                    "Updates",
                    f"Clipper {__version__} is up to date.",
                )
            return
        assert isinstance(release, ReleaseInfo)
        self.update_release = release
        self.update_installer = None
        if release.has_installer:
            self.update_label.setText(
                f"Clipper {release.version} is available · you have {__version__}"
            )
            self.update_action.setText("Download update")
        else:
            self.update_label.setText(
                f"Clipper {release.version} is available · no installer in this release"
            )
            self.update_action.setText("View release")
        self.update_action.setEnabled(True)
        self.update_bar.show()

    def _update_check_failed(self, message: str) -> None:
        self.update_check_worker = None
        if self._manual_update_check:
            self.update_bar.hide()
            show_message(
                self,
                "Update check failed",
                message,
                kind="warning",
                detail="You can also download the latest release from GitHub.",
            )

    def _update_action_clicked(self) -> None:
        if self.update_installer is not None:
            self._install_update()
            return
        release = self.update_release
        if release is None:
            self.check_updates(manual=True)
            return
        if not release.has_installer:
            open_release_page(release)
            return
        self._download_update(release)

    def _download_update(self, release: ReleaseInfo) -> None:
        if self.update_download_worker is not None and self.update_download_worker.isRunning():
            return
        self.update_label.setText(f"Downloading Clipper {release.version}…")
        self.update_action.setText("Downloading…")
        self.update_action.setEnabled(False)
        worker = UpdateDownloadWorker(release)
        worker.progress.connect(self._download_progress)
        worker.ready.connect(self._download_ready)
        worker.failed.connect(self._download_failed)
        worker.finished.connect(worker.deleteLater)
        self.update_download_worker = worker
        worker.start()

    def _download_progress(self, done: int, total: int) -> None:
        release = self.update_release
        label = f"Clipper {release.version}" if release else "update"
        if total > 0:
            percent = min(100, int(done * 100 / total))
            self.update_label.setText(
                f"Downloading {label}… {percent}% "
                f"({done / (1024 * 1024):.0f} of {total / (1024 * 1024):.0f} MB)"
            )
        else:
            self.update_label.setText(f"Downloading {label}… {done / (1024 * 1024):.0f} MB")

    def _download_ready(self, path: str) -> None:
        self.update_download_worker = None
        release = self.update_release
        self.update_installer = Path(path)
        version = release.version if release else ""
        self.update_label.setText(
            f"Update ready · Clipper {version} downloaded and SHA-256 verified"
        )
        self.update_action.setText("Restart and install")
        self.update_action.setEnabled(True)
        self.update_bar.show()

    def _download_failed(self, message: str) -> None:
        self.update_download_worker = None
        self.update_label.setText("Update download failed")
        self.update_action.setText("Retry")
        self.update_action.setEnabled(True)
        self.update_action.setToolTip(message)
        show_message(
            self,
            "Download failed",
            message,
            kind="warning",
            detail="You can download the release manually from GitHub.",
        )

    def _install_update(self) -> None:
        release = self.update_release
        installer = self.update_installer
        if release is None or installer is None:
            return
        if not is_installed_build():
            show_message(
                self,
                "Install update",
                "This copy is not running from the installed Windows build, so "
                "Clipper will open the release page instead of replacing it.",
            )
            open_release_page(release)
            return
        if not ask_confirm(
            self,
            "Install update",
            f"Install Clipper {release.version} now?",
            confirm="Install and restart",
            detail="Clipper will close, install silently, and reopen.",
        ):
            return
        try:
            launch_installer(installer, wait_pid=os.getpid(), relaunch=True)
        except UpdateError as exc:
            show_message(
                self,
                "Could not start installer",
                str(exc),
                kind="critical",
            )
            return
        self.update_label.setText(f"Installing Clipper {release.version}…")
        self.update_action.setEnabled(False)
        self._update_shutdown = True
        QTimer.singleShot(1200, self.close)

    def _update_status(self) -> None:
        if self.ffmpeg_ok:
            self.ffmpeg_label.setText("ffmpeg / ready")
            self.ffmpeg_label.setToolTip(self.ffmpeg_text)
        else:
            self.ffmpeg_label.setText("ffmpeg / missing")
            self.ffmpeg_label.setStyleSheet("color: #e05a5a;")
            self.ffmpeg_label.setToolTip("Install FFmpeg or use the portable build.")
        self._gpu_changed(self.gpu.isChecked())
        self._ai_changed(self.ai.isChecked())

    def _ai_changed(self, checked: bool) -> None:
        running = bool(getattr(self, "_job_running", False))
        mode = str(self.ai_mode.currentData() or "director")
        lite = mode == "lite"
        self.ai.setEnabled(not running)
        self.ai_model.setEnabled(
            not running and checked and not lite and self.vlm_available
        )
        self.ai_game.setEnabled(
            not running and checked and not lite and self.vlm_available
        )
        self.ai_mode.setEnabled(not running and checked)
        self.ai_state.setText("On" if checked else "Off")
        if lite:
            self.ai_state.setToolTip(
                "Lite mode uses local HUD OCR, Whisper, and acoustic/motion signals. "
                "No vision model or extra VRAM is used."
            )
        elif not self.vlm_available:
            self.ai_state.setText("no VLM")
            self.ai_state.setToolTip(
                "Choose Lite mode, or install Ollama and pull qwen2.5vl:7b."
            )
        else:
            self.ai_state.setToolTip(
                "Local AI; GPU when available. Director also transcribes audio locally."
            )

    def _update_ai_setup(self) -> None:
        if not hasattr(self, "ai_setup"):
            return
        self.ai_setup.setVisible(not self.vlm_available)
        if self.vlm_available:
            return
        self.ollama_present = ollama_executable() is not None
        if self.ollama_ok and self.ollama_present:
            self.ai_setup_title.setText("Ollama found · model needed")
            self.ai_setup_text.setText(
                "Lite mode works now. Download a vision model to enable AI Director."
            )
            self.get_ollama_btn.hide()
            self.pull_ai_btn.show()
        elif self.ollama_present:
            self.ai_setup_title.setText("Ollama is installed")
            self.ai_setup_text.setText(
                "Lite mode works now. Start Ollama with Refresh, then download "
                "a vision model to enable AI Director."
            )
            self.get_ollama_btn.hide()
            self.pull_ai_btn.show()
        else:
            self.ai_setup_title.setText("Lite mode is ready")
            self.ai_setup_text.setText(
                "No extra install needed for OCR + Whisper + signal detection. "
                "Clipper can install Ollama for you, then download a local vision model."
            )
            self.get_ollama_btn.show()
            self.pull_ai_btn.hide()
        self.refresh_ai_btn.show()

    def _set_ai_setup_busy(self, busy: bool) -> None:
        for button in (self.get_ollama_btn, self.refresh_ai_btn, self.pull_ai_btn):
            button.setEnabled(not busy)
        self.cancel_ai_btn.setVisible(busy)
        self.cancel_ai_btn.setEnabled(True)
        self.ai_setup_progress.setVisible(busy)
        if not busy:
            self.ai_setup_progress.setValue(0)

    def _install_ollama(self) -> None:
        if self.ai_install_worker is not None and self.ai_install_worker.isRunning():
            return
        self._set_ai_setup_busy(True)
        self.ai_setup_progress.setValue(0)
        self.ai_setup_status.setText("Preparing the official Ollama installer...")
        self.ai_setup_status.show()
        worker = OllamaInstallWorker()
        worker.progress.connect(self._ollama_install_progress)
        worker.status.connect(self._ollama_install_status)
        worker.done.connect(self._ollama_install_done)
        self.ai_install_worker = worker
        worker.start()

    def _cancel_ollama_install(self) -> None:
        worker = self.ai_install_worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            self.cancel_ai_btn.setEnabled(False)
            self.ai_setup_status.setText("Cancelling Ollama download...")

    def _ollama_install_progress(self, done: int, total: int) -> None:
        if total > 0:
            percent = max(0, min(1000, int(done * 1000 / total)))
            self.ai_setup_progress.setValue(percent)
            self.ai_setup_status.setText(
                f"Downloading Ollama: {done / 1e6:.0f} / {total / 1e6:.0f} MB "
                f"({done * 100 // total}%)"
            )
        else:
            self.ai_setup_status.setText(f"Downloading Ollama: {done / 1e6:.0f} MB")

    def _ollama_install_status(self, message: str) -> None:
        self.ai_setup_status.setText(message)
        self.ai_setup_status.show()

    def _ollama_install_done(self, ok: bool, message: str) -> None:
        self.ai_install_worker = None
        self._set_ai_setup_busy(False)
        self.ollama_present = ollama_executable() is not None
        if ok:
            self._refresh_ai_models()
            self.ai_setup_status.setText(message)
            self.ai_setup_status.show()
            return
        self.ai_setup_status.setText(message)
        self.ai_setup_status.show()
        self._update_ai_setup()
        if "cancelled" not in message.lower():
            show_message(self, "Ollama setup failed", message, kind="warning")

    def _refresh_ai_models(self) -> None:
        state = ollama_status(timeout=3)
        if not state.get("ok") and ollama_executable() is not None:
            self.ai_setup_status.setText("Starting Ollama...")
            self.ai_setup_status.show()
            start_ollama_server()
            state = ollama_status(timeout=3)
        self.ollama_ok = bool(state.get("ok"))
        self.ollama_present = ollama_executable() is not None
        installed = {
            str(name).lower(): str(name) for name in state.get("models", [])
        }
        self.installed_models = installed
        vision = [
            name for name in installed.values()
            if any(
                token in name.lower()
                for token in ("vl", "llava", "minicpm", "moondream", "gemma3")
            )
            and not name.lower().startswith("qwen3")
            and "qwen2.5vl:3b" not in name.lower()
        ]
        self.ai_models = vision
        self.vlm_available = bool(vision)
        if self.vlm_available:
            preferred = (
                "gemma3:4b"
                if self.low_vram and "gemma3:4b" in installed
                else (DEFAULT_MODEL if DEFAULT_MODEL.lower() in installed else vision[0])
            )
        else:
            preferred = "No VLM installed (Lite mode)"
        self.ai_default = preferred
        self.ai_model.blockSignals(True)
        self.ai_model.clear()
        for model in self.ai_models or [self.ai_default]:
            self.ai_model.addItem(model)
        index = self.ai_model.findText(self.ai_default)
        if index >= 0:
            self.ai_model.setCurrentIndex(index)
        self.ai_model.blockSignals(False)
        if not self.vlm_available:
            lite_index = self.ai_mode.findData("lite")
            if lite_index >= 0:
                self.ai_mode.setCurrentIndex(lite_index)
        self._update_ai_setup()
        self._ai_changed(self.ai.isChecked())

    def _pull_ai_model(self) -> None:
        if self.pull_worker is not None and self.pull_worker.isRunning():
            return
        if not self.ollama_ok:
            if not self.ollama_present:
                self._update_ai_setup()
                show_message(
                    self,
                    "Ollama is not installed",
                    "Click Install Ollama first. Clipper downloads and verifies it for you.",
                    kind="warning",
                )
                return
            self.ai_setup_status.setText("Starting Ollama...")
            self.ai_setup_status.show()
            self.ollama_ok = start_ollama_server()
            if not self.ollama_ok:
                self._update_ai_setup()
                show_message(
                    self,
                    "Ollama did not start",
                    "Click Refresh to try starting the local Ollama server again.",
                    kind="warning",
                )
                return
        model = "gemma3:4b" if self.low_vram else DEFAULT_MODEL
        size_hint = "about 3.3 GB" if model == "gemma3:4b" else "about 6 GB"
        if not ask_confirm(
            self,
            "Install local AI model",
            f"Download {model} now?",
            confirm="Download",
            detail=(
                f"This is {size_hint} and is downloaded locally through Ollama, "
                "not Clipper. Lite mode already works without it."
            ),
        ):
            return
        self.pull_ai_btn.setEnabled(False)
        self.pull_ai_btn.setText("Starting…")
        self.ai_setup_status.setText(f"Downloading {model}…")
        self.ai_setup_status.show()
        worker = OllamaPullWorker(model)
        worker.line.connect(self._pull_ai_line)
        worker.done.connect(self._pull_ai_done)
        self.pull_worker = worker
        worker.start()

    def _pull_ai_line(self, line: str) -> None:
        self.ai_setup_status.setText(line[:180])

    def _pull_ai_done(self, ok: bool, message: str) -> None:
        self.pull_worker = None
        self.pull_ai_btn.setEnabled(True)
        self.pull_ai_btn.setText("Install model")
        self.ai_setup_status.setText(message)
        if not ok:
            show_message(self, "Model download failed", message, kind="warning")
            return
        self._refresh_ai_models()
        self.ai.setChecked(True)
        director_index = self.ai_mode.findData("director")
        if director_index >= 0:
            self.ai_mode.setCurrentIndex(director_index)
        self._ai_changed(True)
        show_message(
            self,
            "AI Director ready",
            f"{message} The local director is enabled.",
            kind="info",
        )

    def _gpu_changed(self, checked: bool) -> None:
        if not self.nvenc:
            self.gpu_label.setText("nvenc / unavailable")
            self.gpu_label.setStyleSheet("color: #68686f;")
            self.gpu_state.setText("N/A")
            return
        if checked:
            self.gpu_label.setText("nvenc / on")
            self.gpu_label.setStyleSheet("color: #2f9bff;")
            self.gpu_state.setText("On")
        else:
            self.gpu_label.setText("nvenc / off")
            self.gpu_label.setStyleSheet("color: #a1a1a6;")
            self.gpu_state.setText("Off")

    def _sensitivity_changed(self, value: int) -> None:
        self.sensitivity_value.setText(f"{value}%")
        if hasattr(self, "preset_buttons"):
            self.preset_group.setExclusive(False)
            for button, preset in self.preset_buttons:
                button.setChecked(value == preset)
            self.preset_group.setExclusive(True)

    def _toggle_advanced(self, checked: bool) -> None:
        self.advanced.setVisible(checked)
        self.advanced_toggle.setText("Advanced  ▴" if checked else "Advanced  ▾")

    def _low_power_changed(self, checked: bool) -> None:
        self.threads.setEnabled(not checked)
        if checked:
            self.threads.setCurrentIndex(1)
            self.sample_fps.setCurrentIndex(0)
            self.proxy_width.setCurrentIndex(0)

    def _update_encoder_state(self) -> None:
        if not self.reencode.isChecked() and self.encoder.currentData() != "auto":
            self.encoder.blockSignals(True)
            self.encoder.setCurrentIndex(0)
            self.encoder.blockSignals(False)
        self.encoder.setEnabled(True)
        self.crf.setEnabled(self.reencode.isChecked())

    def _encoder_changed(self, _index: int) -> None:
        # Picking a concrete encoder only matters when re-encoding; turn it on
        # instead of leaving a dead-looking control.
        if self.encoder.currentData() != "auto" and not self.reencode.isChecked():
            self.reencode.setChecked(True)
        self._update_encoder_state()

    def _choose_start(self) -> str:
        current = self.input_edit.text().strip()
        if current and Path(current).exists():
            return current
        return str(Path.home())

    # --------------------------------------------------------------- input
    def choose_input(self) -> None:
        menu = QMenu(self)
        folder_action = menu.addAction("Choose folder…")
        video_action = menu.addAction("Choose video…")
        chosen = menu.exec(self.drop.mapToGlobal(QPoint(0, self.drop.height())))
        if chosen is folder_action:
            self.choose_folder()
            return
        if chosen is not video_action:
            return
        start = self._choose_start()
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose gameplay video",
            start,
            "Video files (*.mp4 *.mkv *.mov *.avi);;All files (*.*)",
        )
        if path:
            self.set_input(path, scan=True)

    def choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose gameplay folder", self._choose_start())
        if path:
            self.set_input(path, scan=True)

    def set_input(self, path: str, scan: bool = True) -> None:
        cleaned = str(path).strip().strip('"')
        if not cleaned:
            return
        target = Path(cleaned).expanduser()
        self.input_edit.setText(str(target))
        self.input_edit.setCursorPosition(0)
        # Auto mode resolves each file's game in the pipeline. Do not rewrite
        # the preset here: one NVIDIA parent folder can contain many games.
        if not self.output_edit.text().strip() or self.output_edit.text().strip() == "trimmed":
            base = target.parent if target.is_file() else target
            self.output_edit.setText(str(base / "trimmed"))
        self.summary = None
        self.tree.clear()
        self.preview_player.clear()
        self.export_btn.setEnabled(False)
        self.open_folder.setEnabled(False)
        self.file_list.clear()
        self.file_list.setVisible(False)
        if scan:
            self.scan()

    def scan(self) -> None:
        target = self.input_edit.text().strip()
        if not target:
            show_message(self, "Choose footage", "Pick a folder or drag one onto the drop zone.")
            return
        try:
            files = scan_inputs(target, recursive=self.recursive.isChecked())
        except (ClipperError, OSError) as exc:
            show_message(self, "Scan failed", str(exc), kind="warning")
            return
        self.files = files
        self.file_list.clear()
        for file in files[:200]:
            item = QListWidgetItem(file.name)
            item.setToolTip(str(file))
            self.file_list.addItem(item)
        if files:
            self.file_list.setFixedHeight(min(76, max(38, 24 + 22 * min(len(files), 3))))
        self.file_list.setVisible(bool(files))
        self.summary_label.setText(f"{len(files)} video(s) ready" if files else "No videos found")
        if not files:
            self.status.setText("No supported videos found in that folder.")
        else:
            self.status.setText(f"Ready to analyze {len(files)} video(s).")

    def choose_output(self) -> None:
        start = self.output_edit.text().strip() or self._choose_start()
        path = QFileDialog.getExistingDirectory(self, "Choose output folder", start)
        if path:
            self.output_edit.setText(path)

    # ------------------------------------------------------------- analysis
    def _build_settings(self) -> DetectionSettings:
        settings = DetectionSettings(
            sensitivity=self.sensitivity.value() / 100.0,
            ai_min_confidence=ai_confidence_for_sensitivity(
                self.sensitivity.value() / 100.0
            ),
            pre=float(self.pre.value()),
            post=float(self.post.value()),
            max_clips=self.max_clips.value(),
            sample_fps=float(self.sample_fps.currentData()),
            proxy_width=int(self.proxy_width.currentData()),
            threads=int(self.threads.currentData() or 0),
            gpu=self.gpu.isChecked(),
            preview=True,
            ai=self.ai.isChecked() and self.ai_available,
            ai_model=self.ai_model.currentText().replace(" (not installed)", ""),
            ai_game=str(self.ai_game.currentData() or "generic"),
            ai_mode=str(self.ai_mode.currentData() or "director"),
            game_guard=self._pause_for_game if self.game_guard.isChecked() else None,
        )
        if self.low_power.isChecked():
            settings.apply_low_power()
        return settings

    def analyze(self) -> None:
        if not self.ffmpeg_ok:
            show_message(
                self,
                "FFmpeg missing",
                "Install FFmpeg or use the portable Windows build.",
                kind="critical",
            )
            return
        if self.ai.isChecked() and self.game_guard.isChecked():
            game = self._pause_for_game()
            if game:
                show_message(
                    self,
                    "Gaming detected",
                    f"{game} is running. Clipper paused AI to keep the VRAM free.",
                    kind="warning",
                    detail=(
                        "Close the game and try again, or untick "
                        "'Pause AI while gaming' if you want to analyze anyway."
                    ),
                )
                return
        if not self.files:
            self.scan()
        if not self.files:
            show_message(
                self,
                "No footage",
                "Choose a folder with supported video files first.",
            )
            return
        self.summary = None
        self.tree.clear()
        self.preview_player.clear()
        self.export_btn.setEnabled(False)
        self.open_folder.setEnabled(False)
        self.progress.setValue(0)
        self.status.setText("Starting analysis…")
        self._set_running(True)

        settings = self._build_settings()
        self.worker = AnalyzeWorker(
            self.input_edit.text().strip(),
            settings,
            self.recursive.isChecked(),
            self.preview_dir,
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.file_done.connect(self._on_file_analyzed)
        self.worker.done.connect(self._on_analyzed)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_progress(self, fraction: float, message: str) -> None:
        self.progress.setValue(int(max(0.0, min(1.0, fraction)) * 100))
        self.status.setText(message)

    def _on_file_analyzed(self, analysis) -> None:
        self._live_done += 1
        self._live_clips += len(analysis.clips)
        self._append_analysis(analysis)
        total = self._live_total or self._live_done
        self.summary_label.setText(
            f"{self._live_clips} clips · {self._live_done}/{total} files"
        )
        if analysis.error:
            self.status.setText(f"Scanned {analysis.name}: failed")
        else:
            self.status.setText(f"Scanned {analysis.name}: {len(analysis.clips)} clip(s)")

    def _summary_text(self, clips: int, files: int) -> str:
        clip_word = "clip" if clips == 1 else "clips"
        file_word = "file" if files == 1 else "files"
        return f"{clips} {clip_word} · {files} {file_word}"

    def _on_analyzed(self, summary: AnalysisSummary) -> None:
        self.summary = summary
        self._set_running(False)
        self.progress.setValue(100)
        if self.tree.topLevelItemCount() == 0:
            self._populate(summary)
        else:
            self.summary_label.setText(
                self._summary_text(summary.total_clips, len(summary.files))
            )
            self._update_selection_label()
        self.status.setText(f"Found {summary.total_clips} clip(s) in {len(summary.files)} file(s).")
        self.open_folder.setEnabled(summary.total_clips > 0)
        if self._screenshot_path:
            QTimer.singleShot(1200, self._capture_screenshot)

    def _on_failed(self, message: str) -> None:
        self._set_running(False)
        self.progress.setValue(0)
        if message == "Cancelled":
            self.status.setText("Cancelled.")
        else:
            self.status.setText("Analysis failed.")
            if self._screenshot_path:
                QTimer.singleShot(300, self._capture_screenshot)
            else:
                show_message(self, "Analysis failed", message, kind="critical")

    def _capture_screenshot(self) -> None:
        if self._screenshot_path:
            self._screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            self.grab().save(str(self._screenshot_path))
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _populate(self, summary: AnalysisSummary) -> None:
        self.tree.clear()
        for analysis in summary.files:
            self._append_analysis(analysis, select_first=False)
        self.summary_label.setText(
            self._summary_text(summary.total_clips, len(summary.files))
        )
        self._update_selection_label()
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.data(0, ROLE_VIDEO) is not None:
                self.tree.setCurrentItem(item)
                self._show_preview(item)
                break

    def _append_analysis(self, analysis, select_first: bool = True) -> None:
        self.tree.blockSignals(True)
        first_clip: QTreeWidgetItem | None = None
        if analysis.error:
            item = QTreeWidgetItem(
                ["", analysis.name, "", "", "", "", analysis.error]
            )
            item.setToolTip(1, analysis.path)
            item.setForeground(6, Qt.red)
            self.tree.addTopLevelItem(item)
        else:
            for index, clip in enumerate(analysis.clips):
                item = QTreeWidgetItem(
                    [
                        "",
                        analysis.name,
                        _clock(clip.start),
                        _clock(clip.end),
                        _clock(clip.duration),
                        str(clip.score_pct),
                        clip.reason,
                    ]
                )
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Checked)
                item.setTextAlignment(5, Qt.AlignCenter)
                item.setData(0, ROLE_VIDEO, analysis.path)
                item.setData(0, ROLE_START, float(clip.start))
                item.setData(0, ROLE_END, float(clip.end))
                item.setData(0, ROLE_INDEX, index)
                item.setData(0, ROLE_NAME, analysis.name)
                if index < len(analysis.previews):
                    preview = analysis.previews[index]
                    if Path(preview).is_file():
                        item.setData(0, ROLE_PREVIEW, preview)
                item.setToolTip(0, "Uncheck to exclude this clip from Export selected.")
                item.setToolTip(1, analysis.path)
                item.setToolTip(6, clip.reason)
                self.tree.addTopLevelItem(item)
                if first_clip is None:
                    first_clip = item
        self.tree.blockSignals(False)
        self.select_all_btn.show()
        self.select_none_btn.show()
        self._update_selection_label()
        if select_first and self.tree.currentItem() is None and first_clip is not None:
            self.tree.setCurrentItem(first_clip)
            self._show_preview(first_clip)

    def _clip_check_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column == 0 and item.data(0, ROLE_VIDEO) is not None:
            self._update_selection_label()

    def _set_all_checked(self, checked: bool) -> None:
        self.tree.blockSignals(True)
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.data(0, ROLE_VIDEO) is not None:
                item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
        self.tree.blockSignals(False)
        self._update_selection_label()

    def _update_selection_label(self) -> None:
        total = 0
        selected = 0
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.data(0, ROLE_VIDEO) is None:
                continue
            total += 1
            if item.checkState(0) == Qt.Checked:
                selected += 1
        if total:
            self.selection_label.setText(f"{selected} of {total} selected")
        else:
            self.selection_label.setText("")
        running = self._job_running
        has_summary = bool(self.summary and self.summary.total_clips)
        self.export_btn.setEnabled(selected > 0 and has_summary and not running)
        self.export_all_btn.setEnabled(has_summary and not running)

    def _selected_summary(self) -> AnalysisSummary | None:
        if self.summary is None:
            return None
        selected: dict[str, list[int]] = {}
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.checkState(0) != Qt.Checked:
                continue
            video = item.data(0, ROLE_VIDEO)
            clip_index = item.data(0, ROLE_INDEX)
            if video is None or clip_index is None:
                continue
            selected.setdefault(str(video), []).append(int(clip_index))
        files = []
        for analysis in self.summary.files:
            indices = sorted(set(selected.get(analysis.path, [])))
            if not indices:
                continue
            clips = [analysis.clips[i] for i in indices if i < len(analysis.clips)]
            previews = [
                analysis.previews[i]
                for i in indices
                if i < len(analysis.previews)
            ]
            files.append(replace(analysis, clips=clips, previews=previews))
        if not files:
            return None
        return replace(self.summary, files=files)

    def _tree_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if item is not None and item.data(0, ROLE_VIDEO) is not None:
            self.preview_player.toggle_play()

    def _show_preview(self, current: QTreeWidgetItem | None, previous=None) -> None:
        if current is None or current.data(0, ROLE_VIDEO) is None:
            self.preview_player.clear()
            return
        video = current.data(0, ROLE_VIDEO)
        start = current.data(0, ROLE_START)
        end = current.data(0, ROLE_END)
        poster = current.data(0, ROLE_PREVIEW)
        if not video or start is None or end is None:
            self.preview_player.clear()
            return
        self.preview_player.load(
            str(video),
            float(start),
            float(end),
            str(poster) if poster else None,
        )

    # ---------------------------------------------------------------- export
    def export(self, selected_only: bool = True) -> None:
        summary = self._selected_summary() if selected_only else self.summary
        if not summary or summary.total_clips == 0:
            if selected_only:
                show_message(
                    self,
                    "No clips selected",
                    "Tick at least one clip checkbox, or use Export all.",
                )
            return
        output = self.output_edit.text().strip()
        if not output:
            self.choose_output()
            output = self.output_edit.text().strip()
        if not output:
            show_message(self, "Output folder", "Choose an output folder first.")
            return
        settings = self._build_settings()
        self._set_running(True)
        self.progress.setValue(0)
        self.export_status.setText(
            f"Exporting {summary.total_clips} selected clip(s)…"
            if selected_only
            else f"Exporting all {summary.total_clips} clip(s)…"
        )
        self.export_worker = ExportWorker(
            summary,
            output,
            self.reencode.isChecked(),
            str(self.encoder.currentData()),
            self.crf.value() or 20,
            settings.threads,
        )
        self.export_worker.progress.connect(self._on_progress)
        self.export_worker.done.connect(self._on_exported)
        self.export_worker.failed.connect(self._on_export_failed)
        self.export_worker.start()

    def _on_exported(self, result) -> None:
        self._set_running(False)
        self.progress.setValue(100)
        self.last_output_dir = str(Path(self.output_edit.text().strip()).resolve())
        if result.errors:
            self.export_status.setText(f"{len(result.outputs)} exported, {len(result.errors)} failed.")
            show_message(
                self,
                "Export finished with errors",
                "\n".join(result.errors[:8]),
                kind="warning",
            )
        else:
            self.export_status.setText(f"Exported {len(result.outputs)} clip(s).")
        self.open_folder.setEnabled(True)

    def _on_export_failed(self, message: str) -> None:
        self._set_running(False)
        if message == "Cancelled":
            self.export_status.setText("Export cancelled.")
        else:
            self.export_status.setText("Export failed.")
            show_message(self, "Export failed", message, kind="critical")

    def open_output(self) -> None:
        target = self.last_output_dir or self.output_edit.text().strip()
        if target and Path(target).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(target).resolve())))

    def cancel_current(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
        if self.export_worker and self.export_worker.isRunning():
            self.export_worker.cancel()
        self.status.setText("Cancelling…")

    def _set_running(self, running: bool) -> None:
        self._job_running = running
        self.analyze_btn.setEnabled(not running)
        if running:
            self.export_btn.setEnabled(False)
            self.export_all_btn.setEnabled(False)
        else:
            self._update_selection_label()
        self.reencode.setEnabled(not running)
        self.encoder.setEnabled(not running)
        self.crf.setEnabled(not running and self.reencode.isChecked())
        self.scan_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        self.input_edit.setEnabled(not running)
        self.output_edit.setEnabled(not running)
        self.ai.setEnabled(not running and self.ai_available)
        self._ai_changed(self.ai.isChecked())

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _busy(self) -> bool:
        return bool(
            (self.worker and self.worker.isRunning())
            or (self.export_worker and self.export_worker.isRunning())
            or (self.update_download_worker and self.update_download_worker.isRunning())
        )

    def _pause_for_game(self) -> str | None:
        if not self.game_guard.isChecked():
            return None
        from .gameguard import detect_running_game

        return detect_running_game()

    def _poll_game(self) -> None:
        if not hasattr(self, "game_guard"):
            return
        if not self.game_guard.isChecked():
            self._detected_game = None
            return
        from .gameguard import detect_running_game

        game = detect_running_game()
        if not game:
            self._detected_game = None
            return
        if game == self._detected_game:
            return
        self._detected_game = game
        if not self._busy() and self.ai.isChecked():
            model = self.ai_model.currentText().replace(" (not installed)", "")
            threading.Thread(
                target=unload_model,
                args=(model,),
                daemon=True,
            ).start()

    def eventFilter(self, obj, event):  # noqa: N802
        # Child widgets swallow mouse presses, so the main window never sees a
        # press on the margin over a panel. Watch presses app-wide and start the
        # native resize loop ourselves when the cursor is on this window's edge.
        try:
            if (
                os.name == "nt"
                and event.type() == QEvent.MouseButtonPress
                and event.button() == Qt.LeftButton
                and isinstance(obj, QWidget)
                and obj.window() is self
                and not self.isMaximized()
            ):
                pos = obj.mapTo(self, event.position().toPoint())
                border = 8
                edges = Qt.Edges()
                if pos.x() < border:
                    edges |= Qt.LeftEdge
                elif pos.x() >= self.width() - border:
                    edges |= Qt.RightEdge
                if pos.y() < border:
                    edges |= Qt.TopEdge
                elif pos.y() >= self.height() - border:
                    edges |= Qt.BottomEdge
                if edges:
                    handle = self.windowHandle()
                    if handle is not None and handle.startSystemResize(edges):
                        return True
        except (RuntimeError, TypeError):
            pass
        return False

    def _clamp_to_screen(self) -> None:
        screen = QGuiApplication.screenAt(self.frameGeometry().center())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        # QScreen.availableGeometry() is already in logical pixels. Do not
        # divide by devicePixelRatio here.
        available = screen.availableGeometry()
        min_width = max(320, min(1040, available.width() - 20))
        min_height = max(240, min(720, available.height() - 20))
        self.setMinimumSize(min_width, min_height)
        frame = self.frameGeometry()
        width = max(min(frame.width(), available.width()), min_width)
        height = max(min(frame.height(), available.height()), min_height)
        x = max(available.left(), min(frame.left(), available.right() - width + 1))
        y = max(available.top(), min(frame.top(), available.bottom() - height + 1))
        if (x, y, width, height) != (frame.x(), frame.y(), frame.width(), frame.height()):
            self.setGeometry(x, y, width, height)

    def _position_size_grip(self) -> None:
        if hasattr(self, "size_grip"):
            self.size_grip.move(self.width() - self.size_grip.width() - 2, self.height() - self.size_grip.height() - 2)
            self.size_grip.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._position_size_grip()

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.WindowStateChange and hasattr(self, "max_btn"):
            self.max_btn.setIcon(
                _window_icon("restore" if self.isMaximized() else "max")
            )
        super().changeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if os.name != "nt":
            return
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = int(self.winId())
            get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            get_long.restype = ctypes.c_longlong
            set_long.restype = ctypes.c_longlong
            get_long.argtypes = [ctypes.c_void_p, ctypes.c_int]
            set_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_longlong]
            GWL_STYLE = -16
            WS_THICKFRAME = 0x00040000
            style = get_long(hwnd, GWL_STYLE)
            if not style & WS_THICKFRAME:
                set_long(hwnd, GWL_STYLE, style | WS_THICKFRAME)
                user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020
                )
        except Exception:
            pass
        self._clamp_to_screen()

    def nativeEvent(self, event_type, message):  # noqa: N802
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes

                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084:  # WM_NCHITTEST
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value

                    class POINT(ctypes.Structure):
                        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

                    point = POINT(x, y)
                    ctypes.windll.user32.ScreenToClient(int(self.winId()), ctypes.byref(point))
                    dpr = self.devicePixelRatioF() or 1.0
                    cx = int(point.x / dpr)
                    cy = int(point.y / dpr)
                    width = self.width()
                    height = self.height()
                    border = 6
                    if not self.isMaximized():
                        left = cx < border
                        right = cx >= width - border
                        top = cy < border
                        bottom = cy >= height - border
                        if top and left:
                            return True, 13  # HTTOPLEFT
                        if top and right:
                            return True, 14  # HTTOPRIGHT
                        if bottom and left:
                            return True, 16  # HTBOTTOMLEFT
                        if bottom and right:
                            return True, 17  # HTBOTTOMRIGHT
                        if left:
                            return True, 10  # HTLEFT
                        if right:
                            return True, 11  # HTRIGHT
                        if top:
                            return True, 12  # HTTOP
                        if bottom:
                            return True, 15  # HTBOTTOM
                    # Header is the drag handle, but interactive header controls
                    # must receive their normal clicks at every DPI. Use the
                    # actual laid-out header geometry instead of a fixed height.
                    header = getattr(self, "_header_layout", None)
                    if header is not None and self.centralWidget() is not None:
                        origin = self.centralWidget().mapTo(self, QPoint(0, 0))
                        if header.geometry().translated(origin).contains(QPoint(cx, cy)):
                            widget = self.childAt(QPoint(cx, cy))
                            if isinstance(widget, QAbstractButton):
                                return False
                            return True, 2  # HTCAPTION
            except Exception:
                pass
        return super().nativeEvent(event_type, message)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.preview_player.release_media()
        if self.pull_worker is not None and self.pull_worker.isRunning():
            self.pull_worker.cancel()
            self.pull_worker.wait(3000)
        if self.ai_install_worker is not None and self.ai_install_worker.isRunning():
            self.ai_install_worker.cancel()
            if not self.ai_install_worker.wait(5000):
                self.ai_install_worker.terminate()
                self.ai_install_worker.wait(1000)
        for dialog in self.findChildren(ClipPreviewDialog):
            dialog.close()
        running = bool(
            (self.worker and self.worker.isRunning())
            or (self.export_worker and self.export_worker.isRunning())
        )
        if running:
            if not self._update_shutdown and not ask_confirm(
                self,
                "Quit Clipper?",
                "A job is still running. Cancel it and quit?",
                confirm="Quit",
                kind="warning",
            ):
                event.ignore()
                return
            self.cancel_current()
            terminate_active_processes()
            for worker in (self.worker, self.export_worker):
                if worker and worker.isRunning() and not worker.wait(8000):
                    # Last resort after cancelling and killing FFmpeg children.
                    worker.terminate()
                    worker.wait(1000)
        for worker in (self.update_check_worker, self.update_download_worker):
            if worker and worker.isRunning():
                worker.requestInterruption()
                if not worker.wait(3000):
                    worker.terminate()
                    worker.wait(500)
        if self.update_installer is not None and not self._update_shutdown:
            cleanup_download(self.update_installer)
        terminate_active_processes()
        self._save_settings()
        event.accept()


def apply_theme(app: QApplication) -> None:
    load_app_fonts()
    app.setStyleSheet(
        STYLESHEET
        + f"""
QTreeWidget::indicator, QTreeView::indicator {{
    width: 30px;
    height: 16px;
    border: none;
    background: transparent;
    image: url("{TOGGLE_OFF_ICON}");
}}
QTreeWidget::indicator:checked, QTreeView::indicator:checked {{
    image: url("{TOGGLE_ON_ICON}");
}}
QComboBox {{
    padding-right: 28px;
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 26px;
    border: none;
    background: transparent;
}}
QComboBox::down-arrow {{
    image: url("{CHEVRON_DOWN_ICON}");
    width: 10px;
    height: 6px;
}}
QComboBox::down-arrow:on {{
    image: url("{CHEVRON_UP_ICON}");
}}
QSpinBox {{
    padding-right: 22px;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    width: 20px;
    background: transparent;
    border-left: 1px solid #3b3b3b;
}}
QSpinBox::up-button {{
    subcontrol-position: top right;
    border-top-right-radius: 6px;
}}
QSpinBox::down-button {{
    subcontrol-position: bottom right;
    border-bottom-right-radius: 6px;
}}
QSpinBox::up-arrow {{
    image: url("{CHEVRON_UP_ICON}");
    width: 9px;
    height: 6px;
}}
QSpinBox::down-arrow {{
    image: url("{CHEVRON_DOWN_ICON}");
    width: 9px;
    height: 6px;
}}
"""
    )


def _run_self_test(report_path: str | None) -> int:
    """Verify the frozen AI/OCR runtime without opening the GUI."""

    import json

    from .detect.hud import _engine
    from .detect.signals import _yamnet_session
    from .detect.story import BUNDLED_WHISPER

    result: dict[str, object] = {"version": __version__}
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache")
    download_root = base / "Clipper" / "models" / "huggingface"
    os.environ.setdefault("HF_HOME", str(download_root))
    local_model = (BUNDLED_WHISPER / "model.bin").is_file()
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(
            str(BUNDLED_WHISPER) if local_model else "base.en",
            device="cpu",
            compute_type="int8",
            download_root=str(download_root),
            local_files_only=local_model,
        )
        result["whisper"] = model is not None
        result["whisper_path"] = (
            str(BUNDLED_WHISPER) if local_model else "base.en (cache)"
        )
    except Exception as exc:
        result["whisper"] = False
        result["whisper_error"] = str(exc)

    try:
        result["rapidocr"] = _engine() is not None
    except Exception as exc:
        result["rapidocr"] = False
        result["rapidocr_error"] = str(exc)

    try:
        result["yamnet"] = _yamnet_session(1) is not None
    except Exception as exc:
        result["yamnet"] = False
        result["yamnet_error"] = str(exc)

    try:
        import av
        import cv2
        import onnxruntime

        result["av"] = av.__version__
        result["opencv"] = cv2.__version__
        result["onnxruntime"] = onnxruntime.__version__
        result["providers"] = onnxruntime.get_available_providers()
    except Exception as exc:
        result["runtime_error"] = str(exc)

    if report_path:
        try:
            Path(report_path).write_text(
                json.dumps(result, indent=2), encoding="utf-8"
            )
        except OSError:
            pass
    return 0 if all(result.get(key) for key in ("whisper", "rapidocr", "yamnet")) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clipper-desktop", description="Native Clipper desktop app")
    parser.add_argument("--input", default=None, help="folder or video to preload")
    parser.add_argument("--smoke-test", action="store_true", help="create the window and exit (CI)")
    parser.add_argument("--self-test", default=None, metavar="REPORT", help=argparse.SUPPRESS)
    parser.add_argument("--screenshot", default=None, help="save a window screenshot and exit")
    parser.add_argument("--demo-shot", default=None, help="analyze --input, save a window screenshot, exit")
    parser.add_argument("--story-test", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--story-game", default="generic", help=argparse.SUPPRESS)
    parser.add_argument("--preview-test", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--preview-start", type=float, default=0.0, help=argparse.SUPPRESS)
    parser.add_argument("--preview-end", type=float, default=10.0, help=argparse.SUPPRESS)
    args, qt_args = parser.parse_known_args(argv)

    if args.self_test:
        return _run_self_test(args.self_test)

    if args.story_test:
        import json
        import tempfile

        from .config import DetectionSettings, find_ffmpeg
        from .detect.audio import analyze_wav
        from .detect.story import direct_clip
        from .ffmpeg import extract_audio, probe_media

        if not args.input:
            parser.error("--story-test requires --input")
        try:
            bins = find_ffmpeg()
            video = Path(args.input)
            info = probe_media(video, bins)
            with tempfile.TemporaryDirectory(prefix="clipper_story_test_") as raw:
                wav = extract_audio(video, Path(raw) / "audio.wav", bins, threads=6)
                audio = analyze_wav(wav)
                clips, warnings = direct_clip(
                    video,
                    info.duration,
                    DetectionSettings(
                        ai=True,
                        ai_mode="director",
                        ai_game=args.story_game,
                        max_clips=6,
                    ),
                    wav,
                    audio,
                    bins,
                )
            payload = {
                "clips": [
                    {
                        "start": clip.start,
                        "end": clip.end,
                        "score": clip.score,
                        "reason": clip.reason,
                    }
                    for clip in clips
                ],
                "warnings": warnings,
            }
        except Exception as exc:
            payload = {"error": str(exc)}
            Path(args.story_test).write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return 1
        Path(args.story_test).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return 0

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("Clipper")
    app.setOrganizationName("hatermedia")
    app.setStyle("Fusion")
    app.aboutToQuit.connect(terminate_active_processes)
    apply_theme(app)

    if args.preview_test:
        if not args.input:
            parser.error("--preview-test requires --input")
        dialog = ClipPreviewDialog(
            None,
            args.input,
            args.preview_start,
            args.preview_end,
            "Preview test",
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

        def capture_preview() -> None:
            screen = app.primaryScreen()
            if screen is not None:
                screen.grabWindow(0).save(args.preview_test)
            try:
                Path(args.preview_test).with_suffix(".txt").write_text(
                    f"status={dialog.player.mediaStatus()}\n"
                    f"state={dialog.player.playbackState()}\n"
                    f"error={dialog.error_label.text()}\n",
                    encoding="utf-8",
                )
            except OSError:
                pass
            dialog.close()
            app.quit()

        QTimer.singleShot(4500, capture_preview)
        return app.exec()

    window = MainWindow(initial_input=args.input)
    window.show()

    if args.demo_shot:
        if not args.input:
            parser.error("--demo-shot requires --input")
        window._screenshot_path = Path(args.demo_shot)
        window.set_input(args.input, scan=True)
        QTimer.singleShot(250, window.analyze)
    elif args.smoke_test:
        QTimer.singleShot(250, app.quit)
    elif args.screenshot:
        def capture() -> None:
            window.grab().save(args.screenshot)
            app.quit()

        QTimer.singleShot(900, capture)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
