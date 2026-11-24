"""Native Qt desktop app for Clipper.

This is the primary Windows experience: native folder picker, drag-and-drop,
GPU/NVENC toggle, CPU caps, low-power mode, previews, and export without a
browser or a permanently open command prompt.
"""

from __future__ import annotations

import argparse
import os
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

from PySide6.QtCore import QEvent, QPoint, QSettings, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
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
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .config import (
    Cancelled,
    ClipperError,
    DetectionSettings,
    default_threads,
    find_ffmpeg,
    set_low_priority,
)
from .detect.ai import DEFAULT_MODEL, ollama_status, unload_model
from .ffmpeg import FFmpegError, ffmpeg_version, nvenc_available, nvidia_memory_mb
from .gameguard import detect_running_game
from .models import AnalysisSummary
from .pipeline import analyze_target, export_analysis, scan_inputs
from .update import (
    ReleaseInfo,
    UpdateError,
    check_with_cache,
    download_installer,
    is_installed_build,
    launch_installer,
    open_release_page,
)

ASSET_DIR = Path(__file__).resolve().parent / "assets"
VIDEO_ICON = ASSET_DIR / "icon.png"
ROLE_PREVIEW = int(Qt.UserRole)
ROLE_VIDEO = ROLE_PREVIEW + 1
ROLE_START = ROLE_PREVIEW + 2
ROLE_END = ROLE_PREVIEW + 3
ROLE_INDEX = ROLE_PREVIEW + 4
ROLE_NAME = ROLE_PREVIEW + 5


STYLESHEET = """
QWidget {
    background: #0c0c0e;
    color: #f5f5f7;
    font-family: "Inter";
    font-size: 13px;
}
QMainWindow { background: #0c0c0e; }
QLabel { background: transparent; }
QCheckBox { background: transparent; }
QFrame#Panel {
    background: #121214;
    border: 1px solid #2c2c2e;
    border-radius: 8px;
}
QFrame#DropZone {
    background: #101012;
    border: 1px dashed #38383a;
    border-radius: 6px;
}
QFrame#DropZone:hover { border-color: #4f8bff; }
QLabel#Brand {
    font-family: "IBM Plex Mono";
    font-size: 16px;
    font-weight: 700;
    letter-spacing: 1px;
    color: #ffffff;
}
QLabel#BrandSub {
    font-family: "IBM Plex Mono";
    color: #68686f;
    font-size: 9px;
    letter-spacing: 0.5px;
}
QLabel#Section {
    font-family: "IBM Plex Mono";
    font-size: 10px;
    font-weight: 600;
    color: #a1a1a6;
    letter-spacing: 1px;
}
QLabel#Muted { color: #a1a1a6; font-size: 11px; }
QLabel#Status {
    font-family: "IBM Plex Mono";
    color: #a1a1a6;
    font-size: 10px;
}
QLabel#Summary { color: #a1a1a6; font-size: 11px; }
QLabel#Preview {
    background: #101012;
    border: 1px solid #2c2c2e;
    border-radius: 6px;
    color: #68686f;
}
QPushButton {
    background: #161618;
    border: 1px solid #38383a;
    border-radius: 6px;
    padding: 6px 11px;
    color: #f5f5f7;
    font-weight: 500;
}
QPushButton:hover { background: #1c1c1f; border-color: #4f8bff; }
QPushButton:pressed { background: #101012; }
QPushButton:disabled { color: #68686f; background: #121214; border-color: #2c2c2e; }
QPushButton#Primary {
    background: #f5f5f7;
    color: #0c0c0e;
    font-weight: 600;
    border: none;
    padding: 8px 14px;
}
QPushButton#Primary:hover { background: #ffffff; }
QPushButton#Primary:pressed { background: #d2d2d7; }
QPushButton#Primary:disabled { background: #1c1c1f; color: #68686f; }
QPushButton#Accent {
    background: #3b5cf6;
    color: #ffffff;
    border: none;
    font-weight: 600;
    padding: 6px 12px;
}
QPushButton#Accent:hover { background: #4f8bff; }
QPushButton#Accent:pressed { background: #2f49c9; }
QPushButton#Accent:disabled { background: #1c1c1f; color: #68686f; }
QPushButton#Mono {
    font-family: "IBM Plex Mono";
    font-size: 10px;
    padding: 5px 9px;
}
QPushButton#WindowButton {
    background: transparent;
    border: none;
    color: #a1a1a6;
    font-family: "IBM Plex Mono";
    font-size: 17px;
    padding: 0;
}
QPushButton#WindowButton:hover { background: #1c1c1f; color: #ffffff; }
QPushButton#WindowClose {
    background: transparent;
    border: none;
    color: #a1a1a6;
    font-family: "IBM Plex Mono";
    font-size: 19px;
    padding: 0;
}
QPushButton#WindowClose:hover { background: #c42b1c; color: #ffffff; }
QPushButton#IconButton {
    background: transparent;
    border: none;
    color: #a1a1a6;
    font-size: 16px;
    padding: 0;
}
QPushButton#IconButton:hover { background: #1c1c1f; color: #ffffff; }
QLabel#Help {
    color: #a1a1a6;
    border: 1px solid #38383a;
    border-radius: 7px;
    min-width: 14px;
    max-width: 14px;
    min-height: 14px;
    max-height: 14px;
    font-family: "IBM Plex Mono";
    font-size: 9px;
    background: #121214;
}
QLabel#Help:hover { color: #ffffff; border-color: #4f8bff; background: #1c1c1f; }
QVideoWidget { background: #000000; }
QLabel#PreviewTime {
    font-family: "IBM Plex Mono";
    font-size: 10px;
    color: #a1a1a6;
}
QCheckBox { color: #c7c7cc; spacing: 7px; }
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #48484c;
    border-radius: 3px;
    background: #101012;
}
QCheckBox::indicator:hover { border-color: #4f8bff; }
QCheckBox::indicator:checked { background: #4f8bff; border-color: #4f8bff; }
QFrame#UpdateBar {
    background: #101012;
    border: 1px solid #2c2c2e;
    border-left: 2px solid #4f8bff;
    border-radius: 6px;
}
QFrame#UpdateBar QLabel { color: #c7c7cc; font-size: 12px; }
QFrame#UpdateBar QPushButton { padding: 5px 10px; }
QLineEdit, QComboBox, QSpinBox {
    background: #101012;
    border: 1px solid #38383a;
    border-radius: 6px;
    padding: 6px 8px;
    color: #f5f5f7;
    selection-background-color: #3b5cf6;
    selection-color: #ffffff;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #4f8bff; }
QComboBox QAbstractItemView {
    background: #1c1c1f;
    border: 1px solid #38383a;
    selection-background-color: #2c2c2e;
    selection-color: #ffffff;
    outline: 0;
}
QGroupBox {
    border: 1px solid #2c2c2e;
    border-radius: 6px;
    margin-top: 12px;
    padding: 12px 10px 8px 10px;
    color: #a1a1a6;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    font-family: "IBM Plex Mono";
    font-size: 10px;
    color: #a1a1a6;
    letter-spacing: 1px;
}
QSlider::groove:horizontal { height: 3px; background: #2c2c2e; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 12px; margin: -5px 0; border-radius: 6px;
    background: #f5f5f7;
}
QSlider::handle:horizontal:hover { background: #ffffff; }
QSlider::sub-page:horizontal { background: #4f8bff; border-radius: 2px; }
QProgressBar {
    background: #161618;
    border: none;
    border-radius: 2px;
    text-align: center;
    color: #a1a1a6;
    height: 10px;
    font-size: 9px;
}
QProgressBar::chunk { background: #4f8bff; border-radius: 2px; }
QTreeWidget {
    background: #101012;
    border: 1px solid #2c2c2e;
    border-radius: 6px;
    alternate-background-color: #121214;
    outline: 0;
}
QTreeWidget::item { padding: 5px 4px; border: none; }
QTreeWidget::item:selected { background: #1c1c1f; color: #ffffff; }
QHeaderView::section {
    background: #121214;
    color: #a1a1a6;
    border: 0;
    border-bottom: 1px solid #2c2c2e;
    padding: 6px 8px;
    font-family: "IBM Plex Mono";
    font-size: 10px;
    letter-spacing: 0.5px;
}
QListWidget {
    background: #101012;
    border: 1px solid #2c2c2e;
    border-radius: 6px;
    color: #a1a1a6;
    outline: 0;
}
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #2c2c2e;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #38383a; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent;
    height: 8px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #2c2c2e;
    border-radius: 4px;
    min-width: 24px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QSplitter::handle { background: #0c0c0e; }
QSplitter::handle:hover { background: #1c1c1f; }
QToolTip {
    background: #1c1c1f;
    color: #f5f5f7;
    border: 1px solid #38383a;
    padding: 6px;
    font-size: 11px;
}
QDialog { background: transparent; }
QFrame#DialogPanel {
    background: #161618;
    border: 1px solid #38383a;
    border-radius: 10px;
}
QLabel#DialogTitle {
    font-family: "IBM Plex Mono";
    font-size: 10px;
    font-weight: 600;
    color: #a1a1a6;
    letter-spacing: 1px;
}
QLabel#DialogMessage {
    font-family: "Inter";
    font-size: 14px;
    color: #f5f5f7;
}
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


class DropZone(QFrame):
    pathDropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(68)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)
        title = QLabel("Drop a folder or video here")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #f5f5f7; font-weight: 500;")
        subtitle = QLabel("or use Browse to pick a folder")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setObjectName("Muted")
        layout.addWidget(title)
        layout.addWidget(subtitle)

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


class AppDialog(QDialog):
    """Small OpenCode-style modal used instead of the platform QMessageBox."""

    _ACCENTS = {
        "info": "#4f8bff",
        "warning": "#f4b434",
        "critical": "#ed5a5a",
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

    def closeEvent(self, event) -> None:  # noqa: N802
        self.player.stop()
        self.player.setSource(QUrl())
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
        self.preview_dir = Path(tempfile.mkdtemp(prefix="clipper-desktop-"))
        self.files: list[Path] = []
        self.last_output_dir: str | None = None
        self.nvenc = False
        self._screenshot_path: Path | None = None
        ai_state = ollama_status(timeout=1.5)
        installed = {str(name).lower(): str(name) for name in ai_state.get("models", [])}
        vision = [
            name for name in installed.values()
            if any(token in name.lower() for token in ("vl", "llava", "minicpm", "moondream", "gemma3"))
            and not name.lower().startswith("qwen3")
        ]
        self.ai_models = vision
        self.ai_available = bool(vision)
        self.ai_default = DEFAULT_MODEL if DEFAULT_MODEL.lower() in installed else (vision[0] if vision else DEFAULT_MODEL)
        self.gpu_vram_mb = nvidia_memory_mb()
        self.low_vram = bool(self.gpu_vram_mb and self.gpu_vram_mb <= 7000)
        if self.low_vram and "qwen2.5vl:3b" in installed:
            self.ai_default = "qwen2.5vl:3b"
        self._detected_game: str | None = None
        self.update_release: ReleaseInfo | None = None
        self.update_installer: Path | None = None
        self.update_check_worker: UpdateCheckWorker | None = None
        self.update_download_worker: UpdateDownloadWorker | None = None
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
        outer.setContentsMargins(18, 12, 18, 16)
        outer.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)
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
        github.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/hatermedia/clipper")))
        header.addWidget(github)
        header.addSpacing(8)
        minimize = QPushButton("–")
        minimize.setObjectName("WindowButton")
        minimize.setFixedSize(42, 30)
        minimize.setToolTip("Minimize")
        minimize.clicked.connect(self.showMinimized)
        header.addWidget(minimize)
        self.max_btn = QPushButton("□")
        self.max_btn.setObjectName("WindowButton")
        self.max_btn.setFixedSize(42, 30)
        self.max_btn.setToolTip("Maximize")
        self.max_btn.clicked.connect(self._toggle_maximize)
        header.addWidget(self.max_btn)
        close = QPushButton("×")
        close.setObjectName("WindowClose")
        close.setFixedSize(42, 30)
        close.setToolTip("Close")
        close.clicked.connect(self.close)
        header.addWidget(close)
        outer.addLayout(header)

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
        outer.addWidget(self.update_bar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter, 1)

        # ---------------- left controls ----------------
        left_panel = QFrame()
        left_panel.setObjectName("Panel")
        left_panel.setMinimumWidth(370)
        left_panel.setMaximumWidth(410)
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

        left.addWidget(self._section("01 / FOOTAGE"))
        path_row = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("No folder selected")
        self.input_edit.editingFinished.connect(lambda: self.set_input(self.input_edit.text(), scan=False))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.choose_folder)
        path_row.addWidget(self.input_edit, 1)
        path_row.addWidget(browse)
        left.addLayout(path_row)

        self.drop = DropZone()
        self.drop.pathDropped.connect(lambda p: self.set_input(p, scan=True))
        left.addWidget(self.drop)

        row = QHBoxLayout()
        self.recursive = QCheckBox("Include subfolders")
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
        left.addWidget(self._section("02 / DETECTION"))
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
        for label, value, tip in (
            ("Strict", 32, "Fewer clips, higher confidence."),
            ("Balanced", 50, "The default mix of recall and precision."),
            ("Loose", 78, "More clips; expect more false positives."),
        ):
            button = QPushButton(label)
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, v=value: self.sensitivity.setValue(v))
            presets.addWidget(button)
        left.addLayout(presets)

        pad = QGridLayout()
        pre_labels = QHBoxLayout()
        pre_labels.addWidget(QLabel("Pre-roll (s)"))
        pre_labels.addWidget(
            self._help("Seconds kept before a detected peak. The director trims conversation clips to the spoken exchange instead.")
        )
        pre_labels.addStretch(1)
        pad.addLayout(pre_labels, 0, 0)
        post_labels = QHBoxLayout()
        post_labels.addWidget(QLabel("Post-roll (s)"))
        post_labels.addWidget(
            self._help("Seconds kept after a detected peak. The director uses its own story boundaries for long interactions.")
        )
        post_labels.addStretch(1)
        pad.addLayout(post_labels, 0, 1)
        self.pre = QSpinBox()
        self.pre.setRange(0, 120)
        self.pre.setValue(8)
        self.post = QSpinBox()
        self.post.setRange(0, 120)
        self.post.setValue(5)
        pad.addWidget(self.pre, 1, 0)
        pad.addWidget(self.post, 1, 1)
        left.addLayout(pad)

        ai_row = QHBoxLayout()
        self.ai = QCheckBox("AI director (local)")
        self.ai.setToolTip(
            "The local AI watches the whole clip with audio and sampled frames, "
            "then keeps the funny interactions, banter, reactions, and big plays."
        )
        self.ai_state = QLabel("")
        self.ai_state.setObjectName("Status")
        ai_row.addWidget(self.ai)
        ai_row.addWidget(self.ai_state)
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
        for model in (self.ai_models or [f"{DEFAULT_MODEL} (not installed)"]):
            self.ai_model.addItem(model)
        preferred = self.ai_model.findText(self.ai_default)
        if preferred >= 0:
            self.ai_model.setCurrentIndex(preferred)
        self.ai_model.setEnabled(self.ai_available)
        if self.low_vram:
            self.ai_model.setToolTip(
                f"{self.gpu_vram_mb} MB VRAM detected. Use qwen2.5vl:3b for a 6 GB card."
            )
        ai_controls.addWidget(self.ai_model, 0, 1)
        ai_controls.addWidget(
            self._help(
                "Ollama vision model. qwen2.5vl:7b is the best local default and needs ~6 GB VRAM; "
                "qwen2.5vl:3b is the 6 GB-card fallback and is less accurate."
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
        self.ai_mode.addItem("Review · peaks only", "review")
        self.ai_mode.setToolTip(
            "Director transcribes the audio and watches every window of the clip. "
            "Review is the older, faster pass over audio/motion peaks."
        )
        ai_controls.addWidget(self.ai_mode, 2, 1)
        ai_controls.addWidget(
            self._help(
                "Director: whole-clip audio + frame review, can keep a 30-90s interaction. "
                "Review: only checks the audio/motion peaks, faster but misses context."
            ),
            2,
            2,
        )
        left.addLayout(ai_controls)
        self.ai.setEnabled(self.ai_available)

        game_row = QHBoxLayout()
        self.game_guard = QCheckBox("Pause AI while gaming")
        self.game_guard.setChecked(True)
        self.game_guard.setToolTip(
            "Detects known games and unloads the Ollama model so the game gets the VRAM. "
            "Discord does not expose other games' presence to apps, so Clipper watches "
            "the local process list instead."
        )
        self.game_state = QLabel("")
        self.game_state.setObjectName("Status")
        game_row.addWidget(self.game_guard)
        game_row.addWidget(self.game_state)
        game_row.addWidget(
            self._help(
                "Detects known games from the local process list and unloads the Ollama model "
                "while a game is running. It checks before analysis and between director windows."
            )
        )
        game_row.addStretch(1)
        left.addLayout(game_row)

        gpu_row = QHBoxLayout()
        self.gpu = QCheckBox("Use NVIDIA GPU (NVENC)")
        self.gpu.setToolTip(
            "Hardware decode + NVENC for the analysis proxy and re-encode. "
            "OpenCV motion scoring and audio analysis stay on the CPU."
        )
        self.gpu_state = QLabel("")
        self.gpu_state.setObjectName("Status")
        self.gpu_state.setToolTip("OpenCV motion scoring and audio RMS stay on the CPU.")
        gpu_row.addWidget(self.gpu)
        gpu_row.addWidget(self.gpu_state)
        gpu_row.addWidget(
            self._help(
                "NVENC handles proxy encode and optional re-encode. OpenCV motion scoring "
                "and audio RMS stay on the CPU."
            )
        )
        gpu_row.addStretch(1)
        left.addLayout(gpu_row)
        self.gpu.setEnabled(self.nvenc)

        adv_row = QHBoxLayout()
        self.advanced_toggle = QPushButton("Advanced tuning  ▾")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setToolTip("Max clips, sample rate, proxy size, CPU cap, and low-power mode.")
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        adv_row.addWidget(self.advanced_toggle, 1)
        adv_row.addWidget(
            self._help(
                "Performance and clip-count controls. Low-power mode caps CPU usage while gaming."
            )
        )
        left.addLayout(adv_row)

        self.advanced = QFrame()
        advanced_layout = QGridLayout(self.advanced)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setHorizontalSpacing(8)
        advanced_layout.setVerticalSpacing(7)
        advanced_layout.addWidget(QLabel("Max clips"), 0, 0)
        self.max_clips = QSpinBox()
        self.max_clips.setRange(1, 200)
        self.max_clips.setValue(30)
        advanced_layout.addWidget(self.max_clips, 0, 1)
        advanced_layout.addWidget(QLabel("Sample FPS"), 1, 0)
        self.sample_fps = QComboBox()
        for label, value in (("2 fps", 2.0), ("4 fps", 4.0), ("8 fps", 8.0)):
            self.sample_fps.addItem(label, value)
        self.sample_fps.setCurrentIndex(1)
        advanced_layout.addWidget(self.sample_fps, 1, 1)
        advanced_layout.addWidget(QLabel("Proxy width"), 2, 0)
        self.proxy_width = QComboBox()
        for label, value in (("256 px", 256), ("320 px", 320), ("480 px", 480)):
            self.proxy_width.addItem(label, value)
        self.proxy_width.setCurrentIndex(1)
        advanced_layout.addWidget(self.proxy_width, 2, 1)
        advanced_layout.addWidget(QLabel("CPU threads"), 3, 0)
        self.threads = QComboBox()
        self.threads.addItem("Balanced", default_threads())
        self.threads.addItem("Low (2)", 2)
        self.threads.addItem("Max (all)", 0)
        advanced_layout.addWidget(self.threads, 3, 1)
        self.low_power = QCheckBox("Low-power mode")
        self.low_power.setToolTip("Caps threads at 2, uses a 256px/2fps proxy, and lowers process priority.")
        advanced_layout.addWidget(self.low_power, 4, 0, 1, 2)
        advanced_layout.addWidget(
            QLabel("GPU helps decode/encode; motion scoring remains CPU-bound."),
            5, 0, 1, 2,
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
        results_header.addWidget(self._section("HIGHLIGHTS"))
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
        self.tree.setColumnCount(6)
        self.tree.setHeaderLabels(["CLIP", "START", "END", "LENGTH", "SCORE", "SIGNAL"])
        self.tree.setIconSize(QSize(104, 58))
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(5, QHeaderView.Stretch)
        self.tree.currentItemChanged.connect(self._show_preview)
        self.tree.itemClicked.connect(self._tree_clicked)
        self.tree.itemDoubleClicked.connect(self._tree_double_clicked)
        self.tree.itemChanged.connect(self._clip_check_changed)
        right.addWidget(self.tree, 1)

        self.preview = QLabel("Select a clip to preview its peak frame")
        self.preview.setObjectName("Preview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(170)
        self.preview.setMaximumHeight(210)
        right.addWidget(self.preview)

        export_group = QGroupBox("EXPORT")
        export_layout = QGridLayout(export_group)
        export_layout.setHorizontalSpacing(8)
        export_layout.setVerticalSpacing(7)
        export_layout.addWidget(QLabel("Output"), 0, 0)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Choose an output folder")
        export_layout.addWidget(self.output_edit, 0, 1)
        out_browse = QPushButton("Browse…")
        out_browse.clicked.connect(self.choose_output)
        export_layout.addWidget(out_browse, 0, 2)
        self.reencode = QCheckBox("Frame-accurate re-encode")
        self.reencode.setToolTip("Re-encode for exact cut edges instead of stream copy.")
        self.reencode.toggled.connect(self._update_encoder_state)
        export_layout.addWidget(self.reencode, 1, 0, 1, 2)
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
            "Auto uses stream copy by default and hardware encode when needed. "
            "Choosing a specific encoder turns on frame-accurate re-encode."
        )
        self.encoder.currentIndexChanged.connect(self._encoder_changed)
        export_layout.addWidget(self.encoder, 1, 2)
        export_layout.addWidget(QLabel("CRF"), 2, 0)
        self.crf = QSpinBox()
        self.crf.setRange(0, 51)
        self.crf.setValue(20)
        self.crf.setToolTip("Quality for re-encode; lower is higher quality.")
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
        splitter.setSizes([390, 870])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        self._update_encoder_state()

    def _section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Section")
        return label

    def _help(self, text: str) -> QLabel:
        label = QLabel("?")
        label.setObjectName("Help")
        label.setToolTip(text)
        label.setAlignment(Qt.AlignCenter)
        label.setFixedSize(16, 16)
        label.setCursor(Qt.WhatsThisCursor)
        return label

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
            if stored_model and self.ai_model.findText(stored_model) >= 0:
                if not (self.low_vram and "qwen2.5vl:3b" in self.ai_models):
                    self.ai_model.setCurrentText(stored_model)
            stored_game = str(self.qsettings.value("ai_game", ""))
            if stored_game:
                game_index = self.ai_game.findData(stored_game)
                if game_index >= 0:
                    self.ai_game.setCurrentIndex(game_index)
            stored_mode = str(self.qsettings.value("ai_mode", "director"))
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
        self.update_action.setText("Restart & install")
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
        QTimer.singleShot(1200, QApplication.instance().quit)

    def _update_status(self) -> None:
        if self.ffmpeg_ok:
            self.ffmpeg_label.setText("ffmpeg / ready")
            self.ffmpeg_label.setToolTip(self.ffmpeg_text)
        else:
            self.ffmpeg_label.setText("ffmpeg / missing")
            self.ffmpeg_label.setStyleSheet("color: #ed5a5a;")
            self.ffmpeg_label.setToolTip("Install FFmpeg or use the portable build.")
        self._gpu_changed(self.gpu.isChecked())
        self._ai_changed(self.ai.isChecked())

    def _ai_changed(self, checked: bool) -> None:
        if not self.ai_available:
            self.ai_state.setText("ollama / missing")
            self.ai_state.setToolTip("Install Ollama and run: ollama pull qwen2.5vl:7b")
            self.ai.setEnabled(False)
            return
        self.ai.setEnabled(True)
        self.ai_model.setEnabled(checked)
        self.ai_game.setEnabled(checked)
        self.ai_mode.setEnabled(checked)
        if checked:
            mode = "director" if self.ai_mode.currentData() == "director" else "review"
            self.ai_state.setText(f"{self.ai_model.currentText()} / {mode}")
            self.ai_state.setToolTip("Local AI; GPU when available. Director also transcribes audio locally.")
        else:
            self.ai_state.setText("off")

    def _gpu_changed(self, checked: bool) -> None:
        if not self.nvenc:
            self.gpu_label.setText("nvenc / unavailable")
            self.gpu_label.setStyleSheet("color: #68686f;")
            self.gpu_state.setText("cpu only")
            return
        if checked:
            self.gpu_label.setText("nvenc / on")
            self.gpu_label.setStyleSheet("color: #4f8bff;")
            self.gpu_state.setText("proxy + re-encode")
        else:
            self.gpu_label.setText("nvenc / off")
            self.gpu_label.setStyleSheet("color: #a1a1a6;")
            self.gpu_state.setText("cpu proxy")

    def _sensitivity_changed(self, value: int) -> None:
        self.sensitivity_value.setText(f"{value}%")

    def _toggle_advanced(self, checked: bool) -> None:
        self.advanced.setVisible(checked)
        self.advanced_toggle.setText("Advanced tuning  ▴" if checked else "Advanced tuning  ▾")

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
        self.preview.setText("Select a clip to preview its peak frame")
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
        self.preview.setText("Select a clip to preview its peak frame")
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

    def _on_analyzed(self, summary: AnalysisSummary) -> None:
        self.summary = summary
        self._set_running(False)
        self.progress.setValue(100)
        if self.tree.topLevelItemCount() == 0:
            self._populate(summary)
        else:
            self.summary_label.setText(
                f"{summary.total_clips} clips · {len(summary.files)} files"
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
        self.tree.expandAll()
        self.summary_label.setText(f"{summary.total_clips} clips · {len(summary.files)} files")
        self._update_selection_label()
        for index in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(index)
            if top.childCount():
                self.tree.setCurrentItem(top.child(0))
                break

    def _append_analysis(self, analysis, select_first: bool = True) -> None:
        self.tree.blockSignals(True)
        mono = QFont("IBM Plex Mono")
        mono.setPixelSize(12)
        top = QTreeWidgetItem(
            [
                analysis.name,
                "",
                "",
                "",
                f"{len(analysis.clips)} clips" if not analysis.error else "error",
                analysis.error or "",
            ]
        )
        top.setToolTip(0, analysis.path)
        self.tree.addTopLevelItem(top)
        if analysis.error:
            top.setForeground(5, Qt.red)
        else:
            for index, clip in enumerate(analysis.clips, start=1):
                child = QTreeWidgetItem(
                    [
                        f"{index:02d}",
                        clip.start_label,
                        clip.end_label,
                        clip.duration_label,
                        str(clip.score_pct),
                        clip.reason,
                    ]
                )
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Checked)
                for column in range(5):
                    child.setFont(column, mono)
                child.setTextAlignment(4, Qt.AlignCenter)
                child.setData(0, ROLE_VIDEO, analysis.path)
                child.setData(0, ROLE_START, float(clip.start))
                child.setData(0, ROLE_END, float(clip.end))
                child.setData(0, ROLE_INDEX, index - 1)
                child.setData(0, ROLE_NAME, analysis.name)
                if index - 1 < len(analysis.previews):
                    preview = analysis.previews[index - 1]
                    if Path(preview).is_file():
                        child.setIcon(0, QIcon(preview))
                        child.setData(0, ROLE_PREVIEW, preview)
                child.setToolTip(
                    0,
                    f"{analysis.name} · {clip.start_label}–{clip.end_label} "
                    "· click to preview",
                )
                child.setToolTip(5, clip.reason)
                top.addChild(child)
            top.setExpanded(True)
        self.tree.blockSignals(False)
        self.select_all_btn.show()
        self.select_none_btn.show()
        self._update_selection_label()
        if select_first:
            current = self.tree.currentItem()
            if current is None and top.childCount():
                self.tree.setCurrentItem(top.child(0))
                self._show_preview(top.child(0))

    def _clip_check_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column == 0 and item.parent() is not None:
            self._update_selection_label()

    def _set_all_checked(self, checked: bool) -> None:
        self.tree.blockSignals(True)
        for index in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(index)
            for child_index in range(top.childCount()):
                top.child(child_index).setCheckState(
                    0, Qt.Checked if checked else Qt.Unchecked
                )
        self.tree.blockSignals(False)
        self._update_selection_label()

    def _update_selection_label(self) -> None:
        total = 0
        selected = 0
        for index in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(index)
            for child_index in range(top.childCount()):
                total += 1
                if top.child(child_index).checkState(0) == Qt.Checked:
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
            top = self.tree.topLevelItem(index)
            for child_index in range(top.childCount()):
                child = top.child(child_index)
                if child.checkState(0) != Qt.Checked:
                    continue
                video = child.data(0, ROLE_VIDEO)
                clip_index = child.data(0, ROLE_INDEX)
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

    def _tree_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if item.parent() is not None and column > 0:
            self._open_clip_preview(item)

    def _tree_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if item.parent() is not None:
            self._open_clip_preview(item)

    def _open_clip_preview(self, item: QTreeWidgetItem) -> None:
        video = item.data(0, ROLE_VIDEO)
        start = item.data(0, ROLE_START)
        end = item.data(0, ROLE_END)
        if not video or start is None or end is None:
            return
        name = item.data(0, ROLE_NAME) or ""
        caption = f"{name} · {item.text(1)}–{item.text(2)}"
        ClipPreviewDialog(
            self,
            str(video),
            float(start),
            float(end),
            caption,
            item.text(5),
        ).exec()

    def _show_preview(self, current: QTreeWidgetItem | None, previous=None) -> None:
        if current is None:
            return
        path = current.data(0, Qt.UserRole)
        if not path or not Path(path).is_file():
            return
        pix = QPixmap(str(path))
        if pix.isNull():
            return
        self.preview.setPixmap(
            pix.scaled(self.preview.width() - 16, self.preview.height() - 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.preview.setText("")

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
            self.crf.value(),
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
        self.ai_model.setEnabled(not running and self.ai_available and self.ai.isChecked())
        self.ai_game.setEnabled(not running and self.ai_available and self.ai.isChecked())
        self.ai_mode.setEnabled(not running and self.ai_available and self.ai.isChecked())

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
        if not hasattr(self, "game_state"):
            return
        if not self.game_guard.isChecked():
            self.game_state.setText("guard off")
            self.game_state.setStyleSheet("color: #68686f;")
            self._detected_game = None
            return
        from .gameguard import detect_running_game

        game = detect_running_game()
        if game:
            self.game_state.setText(f"{game} / paused")
            self.game_state.setStyleSheet("color: #f4b434;")
            if game != self._detected_game:
                self._detected_game = game
                if not self._busy() and self.ai.isChecked():
                    model = self.ai_model.currentText().replace(" (not installed)", "")
                    threading.Thread(
                        target=unload_model,
                        args=(model,),
                        daemon=True,
                    ).start()
        else:
            self._detected_game = None
            self.game_state.setText("none")
            self.game_state.setStyleSheet("color: #68686f;")

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.WindowStateChange and hasattr(self, "max_btn"):
            self.max_btn.setText("❐" if self.isMaximized() else "□")
            self.max_btn.setToolTip("Restore" if self.isMaximized() else "Maximize")
        super().changeEvent(event)

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
                    # Header is the drag handle, except the right-side controls.
                    if 0 <= cy < 66 and cx < width - 360:
                        return True, 2  # HTCAPTION
            except Exception:
                pass
        return super().nativeEvent(event_type, message)

    def closeEvent(self, event) -> None:  # noqa: N802
        running = (self.worker and self.worker.isRunning()) or (
            self.export_worker and self.export_worker.isRunning()
        )
        if running:
            if not ask_confirm(
                self,
                "Quit Clipper?",
                "A job is still running. Cancel it and quit?",
                confirm="Quit",
                kind="warning",
            ):
                event.ignore()
                return
            self.cancel_current()
            if self.worker:
                self.worker.wait(5000)
            if self.export_worker:
                self.export_worker.wait(5000)
        for worker in (self.update_check_worker, self.update_download_worker):
            if worker and worker.isRunning():
                worker.requestInterruption()
                if not worker.wait(3000):
                    worker.terminate()
                    worker.wait(500)
        self._save_settings()
        event.accept()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clipper-desktop", description="Native Clipper desktop app")
    parser.add_argument("--input", default=None, help="folder or video to preload")
    parser.add_argument("--smoke-test", action="store_true", help="create the window and exit (CI)")
    parser.add_argument("--screenshot", default=None, help="save a window screenshot and exit")
    parser.add_argument("--demo-shot", default=None, help="analyze --input, save a window screenshot, exit")
    parser.add_argument("--story-test", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--story-game", default="generic", help=argparse.SUPPRESS)
    parser.add_argument("--preview-test", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--preview-start", type=float, default=0.0, help=argparse.SUPPRESS)
    parser.add_argument("--preview-end", type=float, default=10.0, help=argparse.SUPPRESS)
    args, qt_args = parser.parse_known_args(argv)

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
    load_app_fonts()
    app.setStyleSheet(STYLESHEET)

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
